from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from artcode.agent import AgentLoop, AgentRunRequest, NORMAL_AGENT_MODE, RequestPreparer
from artcode.permissions import PermissionState
from artcode.permissions.service import PermissionService
from artcode.persistence import (
    DurablePaths,
    DurablePromptSource,
    MemoryService,
    SessionSelection,
    SessionService,
)
from artcode.prompting.assembler import PromptRequestAssembler
from artcode.providers.events import content_delta_event, done_event, tool_calls_event
from artcode.providers.tool_calls import ToolCall
from artcode.tools import (
    DescriptorBackedTool,
    PreparedToolCall,
    ToolDescriptor,
    ToolEffect,
    ToolEnvironment,
    ToolPreview,
    ToolRegistry,
    success_result,
)
from artcode.tools.execution import ToolExecutionService
from artcode.workspace import ArtCodePaths, Workspace


class ScriptedProvider:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def stream(self, request):
        self.calls.append(request)
        for event in self.responses.pop(0):
            yield event


class ReadProjectTool(DescriptorBackedTool):
    descriptor = ToolDescriptor(
        "read_project",
        "读取项目标记",
        {"type": "object", "properties": {}},
        ToolEffect.READ,
    )

    def prepare(self, arguments, context):
        return PreparedToolCall(self, arguments, ToolPreview(self.name, "read", "project"))

    async def execute(self, prepared, context):
        return success_result(self.name, "ok", "PROJECT TOOL FACT")


async def test_persistence_end_to_end_restores_session_and_new_memory(tmp_path: Path) -> None:
    project_path = tmp_path / "project"
    project_path.mkdir()
    workspace = Workspace.from_path(project_path)
    app_paths = ArtCodePaths.create(tmp_path / "home")
    workspace.project_instruction_file.write_text("PROJECT INSTRUCTION UNIQUE", encoding="utf-8")

    memory_operation = {
        "operations": [
            {
                "action": "create",
                "scope": "project",
                "category": "project_knowledge",
                "target_id": None,
                "title": "工具事实",
                "summary": "PROJECT MEMORY UNIQUE",
                "body": "工具读取到 PROJECT TOOL FACT。",
                "source_entry_ids": ["msg-00000002", "msg-00000005"],
            }
        ]
    }
    first_provider = ScriptedProvider(
        [
            [tool_calls_event([ToolCall("call-1", "read_project", "{}")]), done_event()],
            [content_delta_event("首轮完成"), done_event()],
            [content_delta_event(f"<memory-update>{json.dumps(memory_operation, ensure_ascii=False)}</memory-update>"), done_event()],
        ]
    )
    paths = DurablePaths.from_context(app_paths, workspace)
    first_sessions = SessionService(paths)
    first_session = first_sessions.start(SessionSelection.new())
    first_memory = MemoryService(paths, first_provider)
    session_id = first_session.status.session_id
    registry = ToolRegistry()
    registry.register(ReadProjectTool())
    environment = ToolEnvironment.from_workspace(workspace)
    permission_state = PermissionState()
    first_preparer = RequestPreparer(
        first_session.conversation,
        PromptRequestAssembler(),
        registry,
        environment,
        permission_state,
        durable_prompt=DurablePromptSource(paths),
    )
    first_loop = AgentLoop(
        first_provider,
        first_session.conversation,
        registry,
        environment,
        tool_executor=ToolExecutionService(
            registry,
            environment,
            PermissionService(permission_state),
        ),
        request_preparer=first_preparer,
        natural_turn_observer=first_memory,
        session_id=session_id,
    )

    await _drain(first_loop.run(AgentRunRequest("读取项目", NORMAL_AGENT_MODE)))
    await first_memory.wait_idle()

    assert first_memory.last_report is not None
    assert first_memory.last_report.created == 1
    assert "PROJECT MEMORY UNIQUE" in first_memory.project_store.read_index()
    journal_path = first_sessions.journal.path
    assert [
        json.loads(line)["message"]["role"]
        for line in journal_path.read_text(encoding="utf-8").splitlines()
    ] == ["user", "assistant", "tool", "assistant"]
    await first_memory.close()
    first_sessions.close()

    second_provider = ScriptedProvider(
        [
            [content_delta_event("恢复后继续"), done_event()],
            [content_delta_event("<memory-update>{\"operations\":[]}</memory-update>"), done_event()],
        ]
    )
    resumed_sessions = SessionService(paths)
    resumed = resumed_sessions.start(SessionSelection.resume(session_id))
    resumed_memory = MemoryService(paths, second_provider)
    resumed_state = PermissionState()
    resumed_preparer = RequestPreparer(
        resumed.conversation,
        PromptRequestAssembler(),
        registry,
        environment,
        resumed_state,
        durable_prompt=DurablePromptSource(paths),
    )
    second_loop = AgentLoop(
        second_provider,
        resumed.conversation,
        registry,
        environment,
        tool_executor=ToolExecutionService(
            registry,
            environment,
            PermissionService(resumed_state),
        ),
        request_preparer=resumed_preparer,
        natural_turn_observer=resumed_memory,
        session_id=session_id,
    )
    try:
        assert resumed.status.restored
        assert resumed.status.recovered_messages == 4
        await _drain(second_loop.run(AgentRunRequest("继续", NORMAL_AGENT_MODE)))
        request_messages = second_provider.calls[0].messages
        assert "PROJECT INSTRUCTION UNIQUE" in request_messages[0]["content"]
        assert "PROJECT MEMORY UNIQUE" in request_messages[0]["content"]
        assert any(message.get("content") == "首轮完成" for message in request_messages)
        assert resumed.conversation.export_messages()[-1]["content"] == "恢复后继续"
    finally:
        await resumed_memory.close()
        resumed_sessions.close()


async def _drain(iterator) -> None:
    async for _ in iterator:
        pass


@pytest.mark.ch10_5
@pytest.mark.parametrize(
    "scenario",
    [
        "fresh-new",
        "default-resume",
        "exact-resume",
        "plan-resume",
        "complete-bad-line",
        "incomplete-tail",
        "locked-default",
        "long-gap",
        "instruction-layers",
        "latest-memory-index",
    ],
)
def test_split_session_and_prompt_services_flow(tmp_path: Path, scenario: str) -> None:
    project = tmp_path / "split-project"
    project.mkdir()
    workspace = Workspace.from_path(project)
    paths = DurablePaths.from_context(ArtCodePaths.create(tmp_path / "split-home"), workspace)
    now = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)

    if scenario == "fresh-new":
        service = SessionService(paths)
        context = service.start(SessionSelection.new(), now)
        assert not context.status.restored
        assert service.sessions_summary(1)[0].locked
        service.close()
        return

    if scenario in {"instruction-layers", "latest-memory-index"}:
        paths.local_instruction.write_text("LOCAL FLOW", encoding="utf-8")
        paths.project_instruction.write_text("PROJECT FLOW", encoding="utf-8")
        paths.user_instruction.write_text("USER FLOW", encoding="utf-8")
        source = DurablePromptSource(paths)
        if scenario == "latest-memory-index":
            first = source.build_system_prompt()
            (paths.project_memory_dir / "index.md").write_text(
                "# INDEX AFTER START\n", encoding="utf-8"
            )
            second = source.build_system_prompt()
            assert "INDEX AFTER START" not in first
            assert "INDEX AFTER START" in second
        else:
            prompt = source.build_system_prompt()
            assert prompt.index("LOCAL FLOW") < prompt.index("PROJECT FLOW") < prompt.index("USER FLOW")
        return

    first = SessionService(paths)
    original = first.start(SessionSelection.new(), now)
    original.conversation.append_user("SAFE USER BEFORE", mode="plan")
    original.conversation.append_assistant("SAFE PLAN", mode="plan")
    original.conversation.append_user("SAFE USER AFTER")
    session_id = original.status.session_id
    path = first.journal.path

    if scenario == "locked-default":
        contender = SessionService(paths)
        fallback = contender.start(SessionSelection.latest(), now)
        assert fallback.status.default_locked_new_session
        assert fallback.status.session_id != session_id
        contender.close()
        first.close()
        return

    first.close()
    lines = path.read_bytes().splitlines(keepends=True)
    if scenario == "complete-bad-line":
        path.write_bytes(lines[0] + b"complete-but-bad\n" + b"".join(lines[1:]))
    elif scenario == "incomplete-tail":
        path.write_bytes(b"".join(lines) + b'{"message":')
    elif scenario == "long-gap":
        rewritten = []
        for line in lines:
            payload = json.loads(line)
            payload["timestamp"] = (now - timedelta(hours=25)).isoformat().replace("+00:00", "Z")
            rewritten.append((json.dumps(payload) + "\n").encode())
        path.write_bytes(b"".join(rewritten))

    resumed = SessionService(paths)
    selection = (
        SessionSelection.latest()
        if scenario == "default-resume"
        else SessionSelection.resume(session_id)
    )
    restored = resumed.start(selection, now)
    try:
        users = [
            message["content"]
            for message in restored.conversation.export_messages()
            if message["role"] == "user"
        ]
        assert users == ["SAFE USER BEFORE", "SAFE USER AFTER"]
        assert restored.status.restored
        assert restored.plan_memory.get() == "SAFE PLAN"
        assert restored.status.bad_line_count == int(scenario == "complete-bad-line")
        assert restored.status.truncated is (scenario == "incomplete-tail")
        assert restored.resume_reminder_required is (scenario == "long-gap")
    finally:
        resumed.close()
