from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from artcode.agent import CompletedTurn
from artcode.persistence import DurablePaths, MemoryService, MemoryUpdateReport
from artcode.providers.events import content_delta_event, done_event
from artcode.workspace import ArtCodePaths, Workspace
import artcode.persistence.notes as notes_module


pytestmark = [pytest.mark.ch10_5, pytest.mark.fault]


class UnusedProvider:
    async def stream(self, request):
        if False:
            yield done_event()


class TextProvider:
    def __init__(self, text: str) -> None:
        self.text = text

    async def stream(self, request):
        yield content_delta_event(self.text)
        yield done_event()


def _paths(tmp_path: Path) -> DurablePaths:
    project = tmp_path / "project"
    project.mkdir()
    return DurablePaths.from_context(
        ArtCodePaths.create(tmp_path / "home"), Workspace.from_path(project)
    )


def _turn(summary: dict | None = None) -> CompletedTurn:
    return CompletedTurn(
        "20260810-120000-a1b2",
        "normal",
        "user",
        "reply",
        ("msg-00000002", "msg-00000003"),
        (summary or {},),
    )


async def test_close_cancels_current_update_and_marks_all_dropped_items_done(tmp_path: Path) -> None:
    started = asyncio.Event()
    cancelled = asyncio.Event()

    class HangingUpdater:
        async def update(self, turn):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

    service = MemoryService(_paths(tmp_path), UnusedProvider(), updater=HangingUpdater())
    for _ in range(4):
        service.submit(_turn())
    await started.wait()
    await asyncio.wait_for(service.close(), timeout=1)

    assert cancelled.is_set()
    assert service.pending_count == 0
    await asyncio.wait_for(service.wait_idle(), timeout=1)


async def test_unexpected_updater_exception_does_not_leak_exception_or_secret(tmp_path: Path) -> None:
    secret = "sk-should-never-escape"

    class BrokenUpdater:
        async def update(self, turn):
            raise RuntimeError(secret)

    service = MemoryService(_paths(tmp_path), UnusedProvider(), updater=BrokenUpdater())
    service.submit(_turn())
    await service.wait_idle()
    try:
        assert service.last_report == MemoryUpdateReport(
            "failed", message="记忆后台任务失败，已隔离。"
        )
        assert secret not in str(service.last_report)
    finally:
        await service.close()


async def test_unfreezable_completed_turn_is_rejected_before_queueing(tmp_path: Path) -> None:
    calls = 0

    class CountingUpdater:
        async def update(self, turn):
            nonlocal calls
            calls += 1
            return MemoryUpdateReport("success")

    service = MemoryService(_paths(tmp_path), UnusedProvider(), updater=CountingUpdater())
    service.submit(_turn({"bad": object()}))
    try:
        assert calls == 0
        assert service.pending_count == 0
        assert service.last_report is not None
        assert service.last_report.status == "failed"
    finally:
        await service.close()


async def test_atomic_note_replace_failure_leaves_no_note_or_temp_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operation = {
        "operations": [
            {
                "action": "create",
                "scope": "project",
                "category": "project_knowledge",
                "target_id": None,
                "title": "fact",
                "summary": "summary",
                "body": "body",
                "source_entry_ids": ["msg-00000002", "msg-00000003"],
            }
        ]
    }
    provider = TextProvider(
        "<memory-update>" + json.dumps(operation) + "</memory-update>"
    )
    service = MemoryService(_paths(tmp_path), provider)
    real_replace = notes_module.os.replace

    def fail_note_replace(source, destination):
        if Path(destination).name.startswith("mem-"):
            raise OSError("injected note replace failure")
        return real_replace(source, destination)

    monkeypatch.setattr(notes_module.os, "replace", fail_note_replace)
    service.submit(_turn())
    await service.wait_idle()
    try:
        assert service.last_report is not None
        assert service.last_report.status == "failed"
        assert list(service.project_store.root.glob("mem-*.md")) == []
        assert list(service.project_store.root.glob(".*.tmp")) == []
    finally:
        await service.close()
