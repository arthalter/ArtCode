from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from artcode.agent import AgentEventType, AgentLoop, AgentRunRequest, NORMAL_AGENT_MODE, PLAN_MODE, StopReason
from artcode.conversation import ConversationContext
from artcode.errors import StreamInterruptedError
from artcode.providers.events import content_delta_event, done_event, tool_calls_event
from artcode.providers.tool_calls import ToolCall
from artcode.tools import AllowedPathPolicy, PreparedToolCall, ToolExecutionContext, ToolPreview, ToolRegistry
from artcode.tools.results import ToolResult, error_result, success_result


class FakeProvider:
    def __init__(self, responses: list[list[dict]] | None = None, error: Exception | None = None) -> None:
        self.responses = responses or []
        self.error = error
        self.tools_seen: list[list[dict] | None] = []

    async def stream_chat(self, messages, tools=None):
        self.tools_seen.append(tools)
        if self.error is not None:
            raise self.error
        for event in self.responses.pop(0):
            yield event


class FakeTool:
    description = "fake"
    parameters_schema = {"type": "object", "properties": {}, "additionalProperties": True}

    def __init__(self, name: str, result: ToolResult | None = None) -> None:
        self.name = name
        self.requires_confirmation = False
        self.result = result
        self.executions = 0

    def prepare(self, arguments: dict[str, Any], context: ToolExecutionContext) -> PreparedToolCall | ToolResult:
        if arguments.get("prepare_error"):
            return error_result(self.name, "prepare_error", "预检失败。")
        return PreparedToolCall(self, arguments, ToolPreview(self.name, self.name, self.name, False))

    async def execute(self, prepared: PreparedToolCall, context: ToolExecutionContext) -> ToolResult:
        self.executions += 1
        return self.result or success_result(self.name, f"{self.name} ok")


def context_for(tmp_path: Path) -> ToolExecutionContext:
    return ToolExecutionContext(AllowedPathPolicy((tmp_path,)), default_cwd=tmp_path)


def registry_with(*tools: FakeTool) -> ToolRegistry:
    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool)
    return registry


async def collect(loop: AgentLoop, request: AgentRunRequest):
    return [event async for event in loop.run(request)]


async def test_agent_loop_natural_completion_writes_assistant(tmp_path) -> None:
    context = ConversationContext()
    provider = FakeProvider([[content_delta_event("完成了"), done_event()]])
    loop = AgentLoop(provider, context, registry_with(), context_for(tmp_path))

    events = await collect(loop, AgentRunRequest("你好", NORMAL_AGENT_MODE))

    assert context.export_messages()[-2] == {"role": "user", "content": "你好"}
    assert context.export_messages()[-1] == {"role": "assistant", "content": "完成了"}
    assert provider.tools_seen[0] == []
    assert events[-1].payload["reason"] == StopReason.NATURAL.value


async def test_agent_loop_tool_result_then_next_turn(tmp_path) -> None:
    context = ConversationContext()
    tool = FakeTool("read_file")
    provider = FakeProvider(
        [
            [tool_calls_event([ToolCall("call_1", "read_file", "{}")]), done_event()],
            [content_delta_event("读完了"), done_event()],
        ]
    )
    loop = AgentLoop(provider, context, registry_with(tool), context_for(tmp_path))

    await collect(loop, AgentRunRequest("读文件", NORMAL_AGENT_MODE))

    messages = context.export_messages()
    assert any(message.get("role") == "tool" for message in messages)
    assert messages[-1] == {"role": "assistant", "content": "读完了"}
    assert tool.executions == 1


async def test_text_with_tool_call_is_displayed_but_not_written_as_assistant(tmp_path) -> None:
    context = ConversationContext()
    provider = FakeProvider(
        [
            [content_delta_event("我先看看"), tool_calls_event([ToolCall("call_1", "read_file", "{}")]), done_event()],
            [content_delta_event("总结"), done_event()],
        ]
    )
    loop = AgentLoop(provider, context, registry_with(FakeTool("read_file")), context_for(tmp_path))

    events = await collect(loop, AgentRunRequest("读文件", NORMAL_AGENT_MODE))

    assert any(event.type == AgentEventType.TEXT_DELTA and event.payload["text"] == "我先看看" for event in events)
    assert {"role": "assistant", "content": "我先看看"} not in context.export_messages()


async def test_known_tool_failure_continues_next_turn(tmp_path) -> None:
    context = ConversationContext()
    provider = FakeProvider(
        [
            [tool_calls_event([ToolCall("call_1", "read_file", '{"prepare_error":true}')]), done_event()],
            [content_delta_event("已处理失败"), done_event()],
        ]
    )
    loop = AgentLoop(provider, context, registry_with(FakeTool("read_file")), context_for(tmp_path))

    await collect(loop, AgentRunRequest("读文件", NORMAL_AGENT_MODE))

    tool_message = [message for message in context.export_messages() if message.get("role") == "tool"][0]
    assert json.loads(tool_message["content"])["error_code"] == "prepare_error"
    assert len(provider.tools_seen) == 2


async def test_unknown_tool_stops_and_summarizes_without_tools(tmp_path) -> None:
    context = ConversationContext()
    provider = FakeProvider(
        [
            [tool_calls_event([ToolCall("call_1", "missing_tool", "{}")]), done_event()],
            [content_delta_event("未知工具总结"), done_event()],
        ]
    )
    loop = AgentLoop(provider, context, registry_with(FakeTool("read_file")), context_for(tmp_path))

    events = await collect(loop, AgentRunRequest("未知工具", NORMAL_AGENT_MODE))

    assert events[-1].payload["reason"] == StopReason.UNKNOWN_TOOL.value
    assert provider.tools_seen[1] is None
    payload = json.loads([message for message in context.export_messages() if message.get("role") == "tool"][0]["content"])
    assert payload["error_code"] == "tool_not_found"
    assert context.export_messages()[-1]["content"] == "未知工具总结"


async def test_iteration_limit_stops_at_12_and_summarizes_without_tools(tmp_path) -> None:
    context = ConversationContext()
    provider = FakeProvider(
        [[tool_calls_event([ToolCall(f"call_{i}", "read_file", "{}")]), done_event()] for i in range(12)]
        + [[content_delta_event("达到上限总结"), done_event()]]
    )
    loop = AgentLoop(provider, context, registry_with(FakeTool("read_file")), context_for(tmp_path))

    events = await collect(loop, AgentRunRequest("循环", NORMAL_AGENT_MODE))

    assert [event.payload["current"] for event in events if event.type == AgentEventType.ITERATION_STARTED][-1] == 12
    assert events[-1].payload["reason"] == StopReason.ITERATION_LIMIT.value
    assert provider.tools_seen[-1] is None


async def test_stream_error_does_not_write_partial_text_or_summarize(tmp_path) -> None:
    context = ConversationContext()
    provider = FakeProvider(error=StreamInterruptedError("断开"))
    loop = AgentLoop(provider, context, registry_with(), context_for(tmp_path))

    events = await collect(loop, AgentRunRequest("你好", NORMAL_AGENT_MODE))

    assert events[-1].payload["reason"] == StopReason.STREAM_ERROR.value
    assert context.export_messages()[-1] == {"role": "user", "content": "你好"}
    assert len(provider.tools_seen) == 1


async def test_plan_mode_saves_plan_on_natural_completion(tmp_path) -> None:
    context = ConversationContext()
    provider = FakeProvider([[content_delta_event("计划 A"), done_event()]])
    loop = AgentLoop(provider, context, registry_with(FakeTool("read_file")), context_for(tmp_path))

    await collect(loop, AgentRunRequest("制定计划", PLAN_MODE))

    assert loop.plan_memory.get() == "计划 A"


async def test_plan_mode_disallowed_tool_does_not_execute_or_replace_old_plan(tmp_path) -> None:
    context = ConversationContext()
    tool = FakeTool("write_file")
    provider = FakeProvider(
        [
            [tool_calls_event([ToolCall("call_1", "write_file", "{}")]), done_event()],
            [content_delta_event("不能执行"), done_event()],
        ]
    )
    loop = AgentLoop(provider, context, registry_with(tool), context_for(tmp_path))
    loop.plan_memory.save("旧计划")

    events = await collect(loop, AgentRunRequest("制定计划", PLAN_MODE))

    assert tool.executions == 0
    assert loop.plan_memory.get() == "旧计划"
    assert events[-1].payload["reason"] == StopReason.UNKNOWN_TOOL.value
