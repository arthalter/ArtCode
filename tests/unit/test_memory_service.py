from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest

from artcode.agent import CompletedTurn
from artcode.persistence import (
    DurablePaths,
    MemoryCategory,
    MemoryOperation,
    MemoryScope,
    MemoryService,
    MemoryUpdateReport,
)
from artcode.workspace import ArtCodePaths, Workspace


pytestmark = pytest.mark.ch10_5


class UnusedProvider:
    async def stream_chat(self, messages, tools=None, *, options=None):
        if False:
            yield {}


class RecordingUpdater:
    def __init__(self, result: MemoryUpdateReport | Exception | None = None) -> None:
        self.result = result or MemoryUpdateReport("success")
        self.turns: list[CompletedTurn] = []

    async def update(self, turn: CompletedTurn) -> MemoryUpdateReport:
        self.turns.append(turn)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _paths(tmp_path: Path) -> DurablePaths:
    project = tmp_path / "project"
    project.mkdir()
    return DurablePaths.from_context(
        ArtCodePaths.create(tmp_path / "home"), Workspace.from_path(project)
    )


def _turn(content: str = "user", summary: dict | None = None) -> CompletedTurn:
    return CompletedTurn(
        "20260810-090000-a1b2",
        "normal",
        content,
        "assistant",
        ("msg-00000002", "msg-00000003"),
        (summary or {"name": "read_file", "nested": {"items": [1, 2]}},),
    )


def _service(tmp_path: Path, updater: RecordingUpdater) -> MemoryService:
    return MemoryService(_paths(tmp_path), UnusedProvider(), updater=updater)


def test_memory_service_initializes_both_atomic_indexes(tmp_path: Path) -> None:
    service = _service(tmp_path, RecordingUpdater())
    assert service.user_index_report.active_count == 0
    assert service.project_index_report.active_count == 0
    assert service.user_store.index_path.is_file()
    assert service.project_store.index_path.is_file()


@pytest.mark.parametrize("count", [1, 2, 5])
async def test_memory_service_processes_submissions_fifo(tmp_path: Path, count: int) -> None:
    updater = RecordingUpdater()
    service = _service(tmp_path, updater)
    for index in range(count):
        service.submit(_turn(str(index)))
    await service.wait_idle()
    try:
        assert [turn.user_content for turn in updater.turns] == [str(i) for i in range(count)]
    finally:
        await service.close()


@pytest.mark.parametrize("mutation", ["top", "nested", "list"])
async def test_submit_takes_deep_immutable_snapshot(tmp_path: Path, mutation: str) -> None:
    release = asyncio.Event()

    class BlockingUpdater(RecordingUpdater):
        async def update(self, turn: CompletedTurn) -> MemoryUpdateReport:
            self.turns.append(turn)
            await release.wait()
            return MemoryUpdateReport("success")

    updater = BlockingUpdater()
    service = _service(tmp_path, updater)
    source = {"name": "tool", "nested": {"items": [1, 2]}}
    service.submit(_turn(summary=source))
    source["name"] = "changed"
    source["nested"]["items"].append(3)
    await asyncio.sleep(0)
    snapshot = updater.turns[0].tool_summaries[0]
    try:
        assert snapshot["name"] == "tool"
        assert snapshot["nested"]["items"] == (1, 2)
        with pytest.raises((TypeError, AttributeError)):
            if mutation == "top":
                snapshot["name"] = "x"  # type: ignore[index]
            elif mutation == "nested":
                snapshot["nested"]["x"] = 1  # type: ignore[index]
            else:
                snapshot["nested"]["items"].append(4)
    finally:
        release.set()
        await service.wait_idle()
        await service.close()


async def test_snapshot_failure_is_reported_without_raising_to_agent(tmp_path: Path) -> None:
    updater = RecordingUpdater()
    service = _service(tmp_path, updater)
    reports: list[MemoryUpdateReport] = []
    service.add_callback(reports.append)
    service.submit(_turn(summary={"unsupported": object()}))
    try:
        assert updater.turns == []
        assert reports[-1].status == "failed"
        assert "复制失败" in reports[-1].message
    finally:
        await service.close()


@pytest.mark.parametrize("bad_callback_count", [0, 1, 3])
async def test_callback_failures_are_isolated(
    tmp_path: Path,
    bad_callback_count: int,
) -> None:
    service = _service(tmp_path, RecordingUpdater())
    delivered: list[str] = []
    for _ in range(bad_callback_count):
        service.add_callback(lambda report: (_ for _ in ()).throw(RuntimeError("boom")))
    service.add_callback(lambda report: delivered.append(report.status))
    service.submit(_turn())
    await service.wait_idle()
    try:
        assert delivered == ["success"]
        assert service.last_report == MemoryUpdateReport("success")
    finally:
        await service.close()


@pytest.mark.parametrize("state", ["empty", "active", "queued"])
async def test_close_is_prompt_and_discards_unfinished_work(tmp_path: Path, state: str) -> None:
    cancelled = asyncio.Event()

    class HangingUpdater(RecordingUpdater):
        async def update(self, turn: CompletedTurn) -> MemoryUpdateReport:
            self.turns.append(turn)
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

    updater = HangingUpdater()
    service = _service(tmp_path, updater)
    if state != "empty":
        service.submit(_turn("first"))
        if state == "queued":
            service.submit(_turn("second"))
        await asyncio.sleep(0)
    await asyncio.wait_for(service.close(), timeout=1)
    await asyncio.wait_for(service.wait_idle(), timeout=1)
    service.submit(_turn("ignored"))
    assert service.pending_count == 0
    assert [turn.user_content for turn in updater.turns] == ([] if state == "empty" else ["first"])
    assert cancelled.is_set() is (state != "empty")


@pytest.mark.parametrize("summary_state", ["empty", "active", "superseded"])
def test_memory_summary_reflects_durable_note_state(
    tmp_path: Path,
    summary_state: str,
) -> None:
    service = _service(tmp_path, RecordingUpdater())
    if summary_state != "empty":
        operation = MemoryOperation(
            "create",
            MemoryScope.PROJECT,
            MemoryCategory.PROJECT_KNOWLEDGE,
            title="fact",
            summary="summary",
            body="body",
            source_entry_ids=("msg-00000002",),
        )
        service.project_store.apply(
            [operation],
            datetime(2026, 8, 10, tzinfo=timezone.utc),
            source_session="20260810-090000-a1b2",
        )
        if summary_state == "superseded":
            note_id = service.project_store.scan().notes[0].id
            service.project_store.apply(
                [
                    MemoryOperation(
                        "supersede",
                        MemoryScope.PROJECT,
                        MemoryCategory.PROJECT_KNOWLEDGE,
                        target_id=note_id,
                        source_entry_ids=("msg-00000002",),
                    )
                ]
            )
    summary = service.summary()
    assert summary["project_active"] == int(summary_state == "active")
    assert summary["project_superseded"] == int(summary_state == "superseded")


@pytest.mark.parametrize(
    "result",
    [
        MemoryUpdateReport("success", created=1),
        MemoryUpdateReport("failed", message="provider"),
        RuntimeError("updater crash"),
    ],
    ids=("success", "reported-failure", "unexpected-exception"),
)
async def test_worker_normalizes_last_report(
    tmp_path: Path,
    result: MemoryUpdateReport | Exception,
) -> None:
    service = _service(tmp_path, RecordingUpdater(result))
    service.submit(_turn())
    await service.wait_idle()
    try:
        assert service.last_report is not None
        if isinstance(result, Exception):
            assert service.last_report.status == "failed"
            assert "后台任务失败" in service.last_report.message
        else:
            assert service.last_report == result
    finally:
        await service.close()


@pytest.mark.parametrize("count", [1, 3])
async def test_pending_count_tracks_active_plus_queued(tmp_path: Path, count: int) -> None:
    release = asyncio.Event()

    class BlockingUpdater(RecordingUpdater):
        async def update(self, turn: CompletedTurn) -> MemoryUpdateReport:
            self.turns.append(turn)
            await release.wait()
            return MemoryUpdateReport("success")

    service = _service(tmp_path, BlockingUpdater())
    for index in range(count):
        service.submit(_turn(str(index)))
    await asyncio.sleep(0)
    assert service.pending_count == count
    release.set()
    await service.wait_idle()
    assert service.pending_count == 0
    await service.close()


def test_memory_service_store_scopes_and_paths_are_not_swapped(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    service = MemoryService(paths, UnusedProvider(), updater=RecordingUpdater())
    assert service.user_store.scope is MemoryScope.USER
    assert service.user_store.root == paths.user_memory_dir
    assert service.project_store.scope is MemoryScope.PROJECT
    assert service.project_store.root == paths.project_memory_dir
