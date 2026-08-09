from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from artcode.agent import CompletedTurn
from artcode.persistence import (
    MemoryCategory,
    MemoryNoteStore,
    MemoryScope,
    MemoryUpdateParser,
    MemoryUpdateReport,
    MemoryUpdater,
    MemoryUpdateWorker,
)
from artcode.providers.events import content_delta_event, done_event, tool_calls_event
from artcode.providers.tool_calls import ToolCall


class FakeProvider:
    def __init__(self, text: str, *, tool_calls=()) -> None:
        self.text = text
        self.tool_calls = tool_calls
        self.calls = []

    async def stream(self, request):
        self.calls.append(request)
        yield content_delta_event(self.text)
        if self.tool_calls:
            yield tool_calls_event(self.tool_calls)
        yield done_event()


def _turn() -> CompletedTurn:
    return CompletedTurn(
        session_id="20260806-163000-a1b2",
        mode="normal",
        user_content="以后默认用中文",
        final_text="好的。",
        entry_ids=("msg-00000002", "msg-00000003"),
        tool_summaries=({"name": "read_file", "content": "x" * 5000},),
    )


def _response(operations: list[dict]) -> str:
    return "<memory-update>" + json.dumps({"operations": operations}, ensure_ascii=False) + "</memory-update>"


def _operation(**overrides) -> dict:
    value = {
        "action": "create",
        "scope": "user",
        "category": "preference",
        "target_id": None,
        "title": "默认语言",
        "summary": "用户希望默认使用简体中文交流。",
        "body": "在没有相反要求时使用简体中文回复。",
        "source_entry_ids": ["msg-00000002", "msg-00000003"],
    }
    value.update(overrides)
    return value


def test_parser_requires_unique_strict_tag_schema_and_current_sources() -> None:
    parser = MemoryUpdateParser()

    result = parser.parse(_response([_operation()]), allowed_entry_ids=_turn().entry_ids)

    assert result[0].scope is MemoryScope.USER
    with pytest.raises(ValueError, match="标签外"):
        parser.parse(_response([]) + "outside")
    with pytest.raises(ValueError, match="当前轮之外"):
        parser.parse(_response([_operation(source_entry_ids=["msg-99999999"])]), allowed_entry_ids=_turn().entry_ids)
    with pytest.raises(ValueError, match="工具调用"):
        parser.parse(_response([]), [ToolCall("c", "read_file", "{}")])


def test_parser_rejects_six_operations_user_non_preference_and_oversize() -> None:
    parser = MemoryUpdateParser()
    with pytest.raises(ValueError, match="超过 5"):
        parser.parse(_response([_operation() for _ in range(6)]))
    with pytest.raises(ValueError, match="用户级"):
        parser.parse(_response([_operation(category="correction")]))
    with pytest.raises(ValueError, match="8KB"):
        parser.parse(_response([_operation(body="x" * 9000)]))


async def test_updater_uses_no_tools_disables_thinking_and_applies_both_scopes(tmp_path: Path) -> None:
    operations = [
        _operation(),
        _operation(
            scope="project",
            category="project_knowledge",
            title="运行方式",
            summary="项目是本地 Python CLI。",
            body="ArtCode 通过 Python CLI 在本地运行。",
        ),
    ]
    provider = FakeProvider(_response(operations))
    user = MemoryNoteStore(tmp_path / "user", MemoryScope.USER)
    project = MemoryNoteStore(tmp_path / "project", MemoryScope.PROJECT)

    report = await MemoryUpdater(provider, user, project).update(_turn())

    assert report.status == "success"
    assert report.created == 2
    assert len(user.scan().notes) == 1
    assert len(project.scan().notes) == 1
    request = provider.calls[0]
    assert request.tools is None
    assert request.max_output_tokens == 4000
    assert request.thinking_enabled is False
    assert len(json.loads(request.messages[1]["content"].split("\n", 1)[1].rsplit("\n", 1)[0])["tool_summaries"][0]["content"]) == 2000


async def test_updater_scrubs_known_secret_from_prompt_output_and_disk(tmp_path: Path) -> None:
    secret = "sk-super-secret-value"
    turn = CompletedTurn(**{**_turn().__dict__, "user_content": f"token={secret}"})
    provider = FakeProvider(
        _response([_operation(summary=f"secret {secret}", body=f"body {secret}")])
    )
    user = MemoryNoteStore(tmp_path / "user", MemoryScope.USER)
    project = MemoryNoteStore(tmp_path / "project", MemoryScope.PROJECT)

    report = await MemoryUpdater(provider, user, project, secrets=[secret]).update(turn)

    assert report.created == 1
    assert secret not in str(provider.calls[0].messages)
    assert secret not in next((tmp_path / "user").glob("mem-*.md")).read_text(encoding="utf-8")


async def test_updater_timeout_leaves_notes_unchanged(tmp_path: Path) -> None:
    class HangingProvider:
        async def stream(self, request):
            await asyncio.Event().wait()
            if False:
                yield done_event()

    user = MemoryNoteStore(tmp_path / "user", MemoryScope.USER)
    project = MemoryNoteStore(tmp_path / "project", MemoryScope.PROJECT)

    report = await MemoryUpdater(
        HangingProvider(), user, project, timeout_seconds=0.01
    ).update(_turn())

    assert report.status == "failed"
    assert "30 秒" in report.message
    assert not user.scan().notes


async def test_worker_submit_is_nonblocking_fifo_and_close_cancels(tmp_path: Path) -> None:
    started: list[str] = []
    release = asyncio.Event()

    class FakeUpdater:
        async def update(self, turn):
            started.append(turn.user_content)
            if len(started) == 1:
                await release.wait()
            return MemoryUpdateReport("success", created=1)

    reports = []
    worker = MemoryUpdateWorker(FakeUpdater(), reports.append)
    first = _turn()
    second = CompletedTurn(**{**first.__dict__, "user_content": "second"})

    worker.submit(first)
    worker.submit(second)
    await asyncio.sleep(0)
    assert started == ["以后默认用中文"]
    release.set()
    await asyncio.wait_for(worker._queue.join(), timeout=1)
    assert started == ["以后默认用中文", "second"]
    assert len(reports) == 2
    await worker.close()
