from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from artcode.agent import AgentEventType, AgentLoop as _AgentLoop, AgentRunRequest, NORMAL_AGENT_MODE, PLAN_MODE, RequestPreparer, StopReason
from artcode.conversation import ConversationContext
from artcode.persistence import SessionJournal, MAX_RECORD_BYTES
from artcode.errors import StreamInterruptedError
from artcode.providers.events import content_delta_event, done_event, tool_calls_event
from artcode.providers.tool_calls import ToolCall
from artcode.permissions import PermissionState
from artcode.permissions.service import PermissionService
from artcode.prompting.assembler import PromptRequestAssembler
from artcode.tools import (
    DescriptorBackedTool,
    PreparedToolCall,
    ToolDescriptor,
    ToolEffect,
    ToolEnvironment,
    ToolPreview,
    ToolRegistry,
)
from artcode.tools.execution import ToolExecutionService
from artcode.tools.results import ToolResult, error_result, success_result


class FakeProvider:
    def __init__(self, responses: list[list[dict]] | None = None, error: Exception | None = None) -> None:
        self.responses = responses or []
        self.error = error
        self.tools_seen: list[list[dict] | None] = []
        self.messages_seen: list[list[dict]] = []

    async def stream(self, request):
        self.messages_seen.append(list(request.messages))
        self.tools_seen.append(None if request.tools is None else list(request.tools))
        if self.error is not None:
            raise self.error
        for event in self.responses.pop(0):
            yield event


class FakeTool(DescriptorBackedTool):
    def __init__(self, name: str, result: ToolResult | None = None) -> None:
        effect = ToolEffect.READ if name in {"read_file", "find_files", "search_text"} else ToolEffect.WRITE
        self.descriptor = ToolDescriptor(
            name,
            "fake",
            {"type": "object", "properties": {}, "additionalProperties": True},
            effect,
        )
        self.result = result
        self.executions = 0

    def prepare(self, arguments: dict[str, Any], context) -> PreparedToolCall | ToolResult:
        if arguments.get("prepare_error"):
            return error_result(self.name, "prepare_error", "预检失败。")
        return PreparedToolCall(self, arguments, ToolPreview(self.name, self.name, self.name))

    async def execute(self, prepared: PreparedToolCall, context) -> ToolResult:
        self.executions += 1
        return self.result or success_result(self.name, f"{self.name} ok")


class CancellingTool(FakeTool):
    async def execute(self, prepared: PreparedToolCall, context) -> ToolResult:
        self.executions += 1
        raise asyncio.CancelledError


def context_for(tmp_path: Path) -> ToolEnvironment:
    return ToolEnvironment.from_workspace(tmp_path)


def AgentLoop(
    provider,
    conversation,
    registry,
    environment,
    *,
    context_manager=None,
    natural_turn_observer=None,
    session_id="ephemeral",
):
    permission = PermissionState()
    preparer = RequestPreparer(
        conversation,
        PromptRequestAssembler(),
        registry,
        environment,
        permission,
        context_manager=context_manager,
    )
    return _AgentLoop(
        provider,
        conversation,
        registry,
        environment,
        tool_executor=ToolExecutionService(
            registry,
            environment,
            PermissionService(permission),
        ),
        request_preparer=preparer,
        context_manager=context_manager,
        natural_turn_observer=natural_turn_observer,
        session_id=session_id,
    )


def registry_with(*tools: FakeTool) -> ToolRegistry:
    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool)
    return registry


def is_reminder_message(message: dict[str, Any]) -> bool:
    return message.get("role") == "user" and str(message.get("content", "")).startswith("<system-reminder>")


class EstimateSpy:
    def __init__(self) -> None:
        self.requests = []

    def estimate_request(self, request) -> int:
        self.requests.append(request)
        return 4321


async def collect(loop: _AgentLoop, request: AgentRunRequest):
    return [event async for event in loop.run(request)]


def test_estimate_next_request_is_read_only_and_uses_mode_tool_shape(tmp_path) -> None:
    context = ConversationContext()
    context.append_user("保留原消息")
    read_tool = FakeTool("read_file")
    write_tool = FakeTool("write_file")
    provider = FakeProvider()
    spy = EstimateSpy()
    loop = AgentLoop(
        provider,
        context,
        registry_with(read_tool, write_tool),
        context_for(tmp_path),
        context_manager=spy,
    )
    before = context.export_messages()

    assert loop.estimate_next_request(NORMAL_AGENT_MODE) == 4321
    assert loop.estimate_next_request(PLAN_MODE) == 4321

    assert context.export_messages() == before
    assert provider.messages_seen == []
    assert read_tool.executions == 0
    assert write_tool.executions == 0
    normal_names = [tool["function"]["name"] for tool in spy.requests[0].tools]
    plan_names = [tool["function"]["name"] for tool in spy.requests[1].tools]
    assert normal_names == ["read_file", "write_file"]
    assert plan_names == ["read_file"]


def test_estimate_next_request_is_unavailable_without_context_manager(tmp_path) -> None:
    loop = AgentLoop(FakeProvider(), ConversationContext(), registry_with(), context_for(tmp_path))
    assert loop.estimate_next_request(NORMAL_AGENT_MODE) is None


async def test_agent_loop_natural_completion_writes_assistant(tmp_path) -> None:
    context = ConversationContext()
    provider = FakeProvider([[content_delta_event("完成了"), done_event()]])
    loop = AgentLoop(provider, context, registry_with(), context_for(tmp_path))

    events = await collect(loop, AgentRunRequest("你好", NORMAL_AGENT_MODE))

    assert context.export_messages()[-2] == {"role": "user", "content": "你好"}
    assert context.export_messages()[-1] == {"role": "assistant", "content": "完成了"}
    assert provider.tools_seen[0] == []
    assert events[-1].payload["reason"] == StopReason.NATURAL.value


async def test_agent_loop_appends_system_reminder_to_request_only(tmp_path) -> None:
    context = ConversationContext()
    provider = FakeProvider([[content_delta_event("完成了"), done_event()]])
    loop = AgentLoop(provider, context, registry_with(), context_for(tmp_path))

    await collect(loop, AgentRunRequest("你好", NORMAL_AGENT_MODE))

    assert "<system-reminder>" in provider.messages_seen[0][-1]["content"]
    assert provider.messages_seen[0][-1]["role"] == "user"
    assert not any(is_reminder_message(message) for message in context.export_messages())


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
    assert all("<system-reminder>" in request[-1]["content"] for request in provider.messages_seen)


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
    assert not is_reminder_message(provider.messages_seen[1][-1])
    payload = json.loads([message for message in context.export_messages() if message.get("role") == "tool"][0]["content"])
    assert payload["error_code"] == "tool_not_found"
    assert context.export_messages()[-1]["content"] == "未知工具总结"


async def test_blocked_multi_tool_turn_writes_result_for_every_tool_call(tmp_path) -> None:
    context = ConversationContext()
    valid_tool = FakeTool("read_file")
    provider = FakeProvider(
        [
            [
                tool_calls_event(
                    [
                        ToolCall("call_1", "missing_tool", "{}"),
                        ToolCall("call_2", "read_file", "{}"),
                    ]
                ),
                done_event(),
            ],
            [content_delta_event("已停止。"), done_event()],
        ]
    )
    loop = AgentLoop(provider, context, registry_with(valid_tool), context_for(tmp_path))

    await collect(loop, AgentRunRequest("未知工具", NORMAL_AGENT_MODE))

    tool_messages = [message for message in context.export_messages() if message.get("role") == "tool"]
    payloads = [json.loads(message["content"]) for message in tool_messages]
    assert [message["tool_call_id"] for message in tool_messages] == ["call_1", "call_2"]
    assert [payload["error_code"] for payload in payloads] == ["tool_not_found", "tool_execution_blocked"]
    assert valid_tool.executions == 0
    assert provider.tools_seen[1] is None


async def test_explicit_iteration_limit_stops_at_12_and_summarizes_without_tools(tmp_path) -> None:
    context = ConversationContext()
    provider = FakeProvider(
        [[tool_calls_event([ToolCall(f"call_{i}", "read_file", "{}")]), done_event()] for i in range(12)]
        + [[content_delta_event("达到上限总结"), done_event()]]
    )
    loop = AgentLoop(provider, context, registry_with(FakeTool("read_file")), context_for(tmp_path))

    events = await collect(
        loop,
        AgentRunRequest("循环", NORMAL_AGENT_MODE, max_iterations=12),
    )

    assert [event.payload["current"] for event in events if event.type == AgentEventType.ITERATION_STARTED][-1] == 12
    assert events[-1].payload["reason"] == StopReason.ITERATION_LIMIT.value
    assert provider.tools_seen[-1] is None
    assert not is_reminder_message(provider.messages_seen[-1][-1])


async def test_stream_error_does_not_write_partial_text_or_summarize(tmp_path) -> None:
    context = ConversationContext()
    provider = FakeProvider(error=StreamInterruptedError("断开"))
    loop = AgentLoop(provider, context, registry_with(), context_for(tmp_path))

    events = await collect(loop, AgentRunRequest("你好", NORMAL_AGENT_MODE))

    assert events[-1].payload["reason"] == StopReason.STREAM_ERROR.value
    assert context.export_messages()[-1] == {"role": "user", "content": "你好"}
    assert len(provider.tools_seen) == 1


async def test_cancelled_multi_tool_turn_completes_every_tool_call_and_next_run_is_valid(tmp_path) -> None:
    context = ConversationContext()
    first = FakeTool("write_file")
    second = CancellingTool("edit_file")
    first_provider = FakeProvider(
        [
            [
                tool_calls_event(
                    [
                        ToolCall("call_1", "write_file", "{}"),
                        ToolCall("call_2", "edit_file", "{}"),
                    ]
                ),
                done_event(),
            ]
        ]
    )
    loop = AgentLoop(first_provider, context, registry_with(first, second), context_for(tmp_path))

    events = await collect(loop, AgentRunRequest("执行两个工具", NORMAL_AGENT_MODE))

    assert events[-1].payload["reason"] == StopReason.USER_CANCELLED.value
    tool_messages = [message for message in context.export_messages() if message.get("role") == "tool"]
    assert [message["tool_call_id"] for message in tool_messages] == ["call_1", "call_2"]
    assert json.loads(tool_messages[1]["content"])["error_code"] == "tool_execution_cancelled"

    second_provider = FakeProvider([[content_delta_event("可以继续"), done_event()]])
    next_loop = AgentLoop(second_provider, context, registry_with(first, second), context_for(tmp_path))
    next_events = await collect(next_loop, AgentRunRequest("继续", NORMAL_AGENT_MODE))

    assert next_events[-1].payload["reason"] == StopReason.NATURAL.value
    sent = second_provider.messages_seen[0]
    assistant_index = next(index for index, message in enumerate(sent) if message.get("tool_calls"))
    assert [sent[assistant_index + offset]["tool_call_id"] for offset in (1, 2)] == ["call_1", "call_2"]


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


async def test_natural_turn_observer_runs_after_journaled_final_message(tmp_path) -> None:
    observed_entries = []

    class EntryObserver:
        def on_entry(self, entry):
            observed_entries.append(entry)

    turns = []

    class TurnObserver:
        def submit(self, turn):
            assert observed_entries[-1].payload == {"role": "assistant", "content": "读完了"}
            turns.append(turn)

    context = ConversationContext(observer=EntryObserver())
    tool = FakeTool("read_file", success_result("read_file", "ok", "file body"))
    provider = FakeProvider(
        [
            [tool_calls_event([ToolCall("call_1", "read_file", "{}")]), done_event()],
            [content_delta_event("读完了"), done_event()],
        ]
    )
    loop = AgentLoop(
        provider,
        context,
        registry_with(tool),
        context_for(tmp_path),
        natural_turn_observer=TurnObserver(),
        session_id="20260806-163000-a1b2",
    )

    await collect(loop, AgentRunRequest("读文件", NORMAL_AGENT_MODE))

    assert [entry.mode for entry in observed_entries] == ["normal"] * 4
    assert len(turns) == 1
    assert turns[0].entry_ids == tuple(entry.id for entry in observed_entries)
    assert turns[0].tool_summaries[0]["name"] == "read_file"
    assert turns[0].tool_summaries[0]["content"] == "file body"


async def test_abnormal_summary_does_not_submit_natural_memory_turn(tmp_path) -> None:
    turns = []
    provider = FakeProvider(
        [
            [tool_calls_event([ToolCall("call_1", "missing", "{}")]), done_event()],
            [content_delta_event("异常总结"), done_event()],
        ]
    )
    loop = AgentLoop(
        provider,
        ConversationContext(),
        registry_with(),
        context_for(tmp_path),
        natural_turn_observer=type("Observer", (), {"submit": lambda self, turn: turns.append(turn)})(),
    )

    await collect(loop, AgentRunRequest("请求", NORMAL_AGENT_MODE))

    assert turns == []


def test_entry_observer_failure_marks_entry_without_rolling_back() -> None:
    class BrokenObserver:
        def on_entry(self, entry):
            raise OSError("disk full")

    context = ConversationContext(observer=BrokenObserver())

    entry = context.append_user("仍保留")

    assert entry.persistence_failed
    assert context.export_messages()[-1]["content"] == "仍保留"
    assert isinstance(context.last_observer_error, OSError)


async def test_oversized_user_message_is_rejected_before_provider_request(tmp_path) -> None:
    journal = SessionJournal.create(tmp_path / "sessions")
    context = ConversationContext(observer=journal)
    provider = FakeProvider([])
    loop = AgentLoop(provider, context, registry_with(), context_for(tmp_path))
    try:
        events = await collect(
            loop,
            AgentRunRequest("x" * (MAX_RECORD_BYTES + 1), NORMAL_AGENT_MODE),
        )
        assert events[-1].payload["reason"] == StopReason.STREAM_ERROR.value
        assert "4MB" in events[-1].payload["message"]
        assert provider.messages_seen == []
        assert len(context.export_messages()) == 1
    finally:
        journal.close()
