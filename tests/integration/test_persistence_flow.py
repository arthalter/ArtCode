from __future__ import annotations

import json
from pathlib import Path

from artcode.agent import AgentLoop, AgentRunRequest, NORMAL_AGENT_MODE
from artcode.persistence import PersistenceCoordinator, SessionSelection
from artcode.prompting.assembler import PromptRequestAssembler
from artcode.providers.events import content_delta_event, done_event, tool_calls_event
from artcode.providers.tool_calls import ToolCall
from artcode.tools import (
    AllowedPathPolicy,
    PreparedToolCall,
    ToolExecutionContext,
    ToolPreview,
    ToolRegistry,
    success_result,
)
from artcode.workspace import ArtCodePaths, Workspace


class ScriptedProvider:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def stream_chat(self, messages, tools=None, *, options=None):
        self.calls.append((list(messages), tools, options))
        for event in self.responses.pop(0):
            yield event


class ReadProjectTool:
    name = "read_project"
    description = "读取项目标记"
    parameters_schema = {"type": "object", "properties": {}}
    requires_confirmation = False

    def prepare(self, arguments, context):
        return PreparedToolCall(self, arguments, ToolPreview(self.name, "read", "project", False))

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
    first = PersistenceCoordinator.start(
        app_paths, workspace, first_provider, SessionSelection.new()
    )
    session_id = first.status.session_id
    registry = ToolRegistry()
    registry.register(ReadProjectTool())
    tool_context = ToolExecutionContext(
        AllowedPathPolicy((workspace.root,)), default_cwd=workspace.root
    )
    first_loop = AgentLoop(
        first_provider,
        first.conversation,
        registry,
        tool_context,
        request_assembler=PromptRequestAssembler(durable_prompt=first.prompt_context),
        natural_turn_observer=first.turn_observer,
        session_id=session_id,
    )

    await _drain(first_loop.run(AgentRunRequest("读取项目", NORMAL_AGENT_MODE)))
    await first.memory_worker._queue.join()

    assert first.last_memory_report is not None
    assert first.last_memory_report.created == 1
    assert "PROJECT MEMORY UNIQUE" in first.project_notes.read_index()
    journal_path = first.journal.path
    assert [
        json.loads(line)["message"]["role"]
        for line in journal_path.read_text(encoding="utf-8").splitlines()
    ] == ["user", "assistant", "tool", "assistant"]
    await first.close()

    second_provider = ScriptedProvider(
        [
            [content_delta_event("恢复后继续"), done_event()],
            [content_delta_event("<memory-update>{\"operations\":[]}</memory-update>"), done_event()],
        ]
    )
    resumed = PersistenceCoordinator.start(
        app_paths,
        workspace,
        second_provider,
        SessionSelection.resume(session_id),
    )
    second_loop = AgentLoop(
        second_provider,
        resumed.conversation,
        registry,
        tool_context,
        request_assembler=PromptRequestAssembler(durable_prompt=resumed.prompt_context),
        natural_turn_observer=resumed.turn_observer,
        session_id=session_id,
    )
    try:
        assert resumed.status.restored
        assert resumed.status.recovered_messages == 4
        await _drain(second_loop.run(AgentRunRequest("继续", NORMAL_AGENT_MODE)))
        request_messages = second_provider.calls[0][0]
        assert "PROJECT INSTRUCTION UNIQUE" in request_messages[0]["content"]
        assert "PROJECT MEMORY UNIQUE" in request_messages[0]["content"]
        assert any(message.get("content") == "首轮完成" for message in request_messages)
        assert resumed.conversation.export_messages()[-1]["content"] == "恢复后继续"
    finally:
        await resumed.close()


async def _drain(iterator) -> None:
    async for _ in iterator:
        pass
