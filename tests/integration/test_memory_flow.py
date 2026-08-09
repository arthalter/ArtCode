from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from artcode.agent import CompletedTurn
from artcode.persistence import (
    DurablePaths,
    DurablePromptSource,
    MemoryCategory,
    MemoryOperation,
    MemoryScope,
    MemoryService,
    SessionSelection,
    SessionService,
)
from artcode.providers.events import content_delta_event, done_event, tool_calls_event
from artcode.providers.tool_calls import ToolCall
from artcode.workspace import ArtCodePaths, Workspace


pytestmark = pytest.mark.ch10_5


class ResponseProvider:
    def __init__(self, response: str, *, include_tool_call: bool = False) -> None:
        self.response = response
        self.include_tool_call = include_tool_call

    async def stream_chat(self, messages, tools=None, *, options=None):
        yield content_delta_event(self.response)
        if self.include_tool_call:
            yield tool_calls_event([ToolCall("memory-tool", "read_file", "{}")])
        yield done_event()


class FailingProvider:
    def __init__(self, mode: str) -> None:
        self.mode = mode

    async def stream_chat(self, messages, tools=None, *, options=None):
        if self.mode == "timeout":
            await asyncio.Event().wait()
        raise RuntimeError("provider exploded")
        if False:
            yield done_event()


def _paths(tmp_path: Path) -> DurablePaths:
    project = tmp_path / "project"
    project.mkdir()
    return DurablePaths.from_context(
        ArtCodePaths.create(tmp_path / "home"), Workspace.from_path(project)
    )


def _turn(content: str = "remember") -> CompletedTurn:
    return CompletedTurn(
        "20260810-120000-a1b2",
        "normal",
        content,
        "done",
        ("msg-00000002", "msg-00000003"),
    )


def _operation(
    *,
    scope: str = "project",
    action: str = "create",
    target_id: str | None = None,
) -> dict:
    return {
        "action": action,
        "scope": scope,
        "category": "preference" if scope == "user" else "project_knowledge",
        "target_id": target_id,
        "title": "flow fact",
        "summary": "MEMORY FLOW INDEX FACT",
        "body": "durable flow body",
        "source_entry_ids": ["msg-00000002", "msg-00000003"],
    }


def _xml(operations: list[dict]) -> str:
    return "<memory-update>" + json.dumps({"operations": operations}) + "</memory-update>"


@pytest.mark.parametrize(
    "case",
    ["project-create", "user-create", "dual-create", "noop", "update-existing"],
)
async def test_memory_provider_store_index_and_prompt_flow(tmp_path: Path, case: str) -> None:
    paths = _paths(tmp_path)
    existing_id = None
    if case == "update-existing":
        seed = MemoryService(paths, ResponseProvider(_xml([])))
        seed.project_store.apply(
            [
                MemoryOperation(
                    "create",
                    MemoryScope.PROJECT,
                    MemoryCategory.PROJECT_KNOWLEDGE,
                    title="old",
                    summary="old",
                    body="old",
                    source_entry_ids=("msg-00000002",),
                )
            ],
            source_session="20260810-120000-a1b2",
        )
        existing_id = seed.project_store.scan().notes[0].id
        await seed.close()

    operations = {
        "project-create": [_operation()],
        "user-create": [_operation(scope="user")],
        "dual-create": [_operation(), _operation(scope="user")],
        "noop": [
            {
                **_operation(action="noop"),
                "title": "",
                "summary": "",
                "body": "",
            }
        ],
        "update-existing": [_operation(action="update", target_id=existing_id)],
    }[case]
    service = MemoryService(paths, ResponseProvider(_xml(operations)))
    source = DurablePromptSource(paths)
    before = source.build_system_prompt()
    service.submit(_turn(case))
    await service.wait_idle()
    after = source.build_system_prompt()
    try:
        assert service.last_report is not None
        assert service.last_report.status == "success"
        expected_created = 2 if case == "dual-create" else 0 if case in {"noop", "update-existing"} else 1
        assert service.last_report.created == expected_created
        assert service.last_report.updated == int(case == "update-existing")
        if case != "noop":
            assert "MEMORY FLOW INDEX FACT" in after
        if case in {"project-create", "user-create", "dual-create"}:
            assert "MEMORY FLOW INDEX FACT" not in before
    finally:
        await service.close()


@pytest.mark.parametrize(
    "failure",
    ["timeout", "provider", "invalid-xml", "tool-call", "storage"],
)
async def test_memory_failures_do_not_touch_session_or_current_reply(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    paths = _paths(tmp_path)
    sessions = SessionService(paths)
    session = sessions.start(SessionSelection.new())
    session.conversation.append_user("current user")
    session.conversation.append_assistant("current reply")
    before_messages = session.conversation.export_messages()
    before_journal = sessions.journal.path.read_bytes()

    if failure in {"timeout", "provider"}:
        provider = FailingProvider(failure)
    elif failure == "invalid-xml":
        provider = ResponseProvider("not xml")
    elif failure == "tool-call":
        provider = ResponseProvider(_xml([]), include_tool_call=True)
    else:
        provider = ResponseProvider(_xml([_operation()]))
    memory = MemoryService(paths, provider)
    if failure == "timeout":
        memory.updater.timeout_seconds = 0.01
    if failure == "storage":
        monkeypatch.setattr(
            memory.project_store,
            "apply",
            lambda *args, **kwargs: (_ for _ in ()).throw(OSError("disk full")),
        )

    memory.submit(_turn(failure))
    await memory.wait_idle()
    try:
        assert memory.last_report is not None
        assert memory.last_report.status == "failed"
        assert session.conversation.export_messages() == before_messages
        assert sessions.journal.path.read_bytes() == before_journal
        assert session.conversation.export_messages()[-1]["content"] == "current reply"
    finally:
        await memory.close()
        sessions.close()
