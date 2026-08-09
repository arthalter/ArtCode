from __future__ import annotations

import pytest

from artcode.agent import (
    AgentEventType,
    AgentLoop,
    AgentRunRequest,
    NORMAL_AGENT_MODE,
    RequestPreparer,
    StopReason,
)
from artcode.conversation import ConversationContext
from artcode.errors import NetworkError
from artcode.permissions import PermissionState
from artcode.permissions.service import PermissionService
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

pytestmark = pytest.mark.ch10_5


class ScriptedProvider:
    def __init__(self, actions) -> None:
        self.actions = list(actions)
        self.requests = []

    async def stream(self, request):
        self.requests.append(request)
        action = self.actions.pop(0)
        if isinstance(action, Exception):
            raise action
        for event in action:
            yield event


class CountingTool(DescriptorBackedTool):
    descriptor = ToolDescriptor(
        "read_file",
        "read",
        {"type": "object", "properties": {}},
        ToolEffect.READ,
    )

    def __init__(self) -> None:
        self.executions = 0

    def prepare(self, arguments, context):
        return PreparedToolCall(self, arguments, ToolPreview(self.name, "read", "read"))

    async def execute(self, prepared, context):
        self.executions += 1
        return success_result(self.name, "ok")


class DurableSource:
    def __init__(self, *, fails: bool = False) -> None:
        self.fails = fails

    def build_system_prompt(self) -> str:
        if self.fails:
            raise RuntimeError("durable unavailable")
        return "DURABLE"


def build(tmp_path, provider, *, reminder=False, durable=None):
    conversation = ConversationContext()
    environment = ToolEnvironment.from_workspace(tmp_path)
    permission_state = PermissionState()
    registry = ToolRegistry()
    tool = CountingTool()
    registry.register(tool)
    preparer = RequestPreparer(
        conversation,
        PromptRequestAssembler(),
        registry,
        environment,
        permission_state,
        durable_prompt=durable,
        resume_reminder_required=reminder,
    )
    loop = AgentLoop(
        provider,
        conversation,
        registry,
        environment,
        tool_executor=ToolExecutionService(
            registry,
            environment,
            PermissionService(permission_state),
        ),
        request_preparer=preparer,
    )
    return loop, preparer, conversation, tool


async def drain(loop, request):
    return [event async for event in loop.run(request)]


def tool_chain(length: int):
    return [
        [tool_calls_event([ToolCall(f"call-{index}", "read_file", "{}")]), done_event("tool_calls")]
        for index in range(length)
    ]


@pytest.mark.parametrize("chain_length", [13, 14, 20], ids=("thirteen", "fourteen", "twenty"))
async def test_default_loop_continues_past_the_removed_twelve_turn_limit(tmp_path, chain_length: int) -> None:
    provider = ScriptedProvider(tool_chain(chain_length) + [[content_delta_event("done"), done_event("stop")]])
    loop, _, _, tool = build(tmp_path, provider)

    events = await drain(loop, AgentRunRequest("continue", NORMAL_AGENT_MODE))

    iterations = [event.payload["current"] for event in events if event.type is AgentEventType.ITERATION_STARTED]
    assert iterations[-1] == chain_length + 1
    assert tool.executions == chain_length
    assert events[-1].payload["reason"] == StopReason.NATURAL.value


@pytest.mark.parametrize("maximum", [1, 2, 5, 12], ids=("one", "two", "five", "twelve"))
async def test_explicit_positive_limit_remains_deterministic(tmp_path, maximum: int) -> None:
    provider = ScriptedProvider(tool_chain(maximum))
    loop, _, _, tool = build(tmp_path, provider)

    events = await drain(
        loop,
        AgentRunRequest(
            "bounded",
            NORMAL_AGENT_MODE,
            max_iterations=maximum,
            final_summary_on_abnormal_stop=False,
        ),
    )

    assert len(provider.requests) == maximum
    assert tool.executions == maximum
    assert events[-1].payload["reason"] == StopReason.ITERATION_LIMIT.value


@pytest.mark.parametrize("text", ["partial", "部分文本", ""], ids=("ascii", "unicode", "empty"))
async def test_length_finish_preserves_only_actual_text_and_never_auto_continues(tmp_path, text: str) -> None:
    provider = ScriptedProvider([[content_delta_event(text), done_event("length")]])
    loop, _, conversation, _ = build(tmp_path, provider)

    events = await drain(loop, AgentRunRequest("write", NORMAL_AGENT_MODE))

    assert len(provider.requests) == 1
    assert events[-1].payload["reason"] == StopReason.NATURAL.value
    assistant = [message["content"] for message in conversation.export_messages() if message["role"] == "assistant"]
    assert assistant == ([text] if text else [])


@pytest.mark.parametrize("preview_count", [1, 3, 10], ids=("one", "three", "ten"))
async def test_any_number_of_previews_still_sends_resume_reminder_exactly_once(tmp_path, preview_count: int) -> None:
    provider = ScriptedProvider(
        tool_chain(1) + [[content_delta_event("done"), done_event("stop")]]
    )
    loop, preparer, _, _ = build(tmp_path, provider, reminder=True)
    for _ in range(preview_count):
        assert preparer.preview_request(NORMAL_AGENT_MODE).includes_resume_reminder

    await drain(loop, AgentRunRequest("continue", NORMAL_AGENT_MODE))

    assert "超过 24 小时" in str(provider.requests[0].messages)
    assert "超过 24 小时" not in str(provider.requests[1].messages)
    assert not preparer.resume_reminder_pending


async def test_preparation_failure_does_not_dispatch_or_consume_resume_reminder(tmp_path) -> None:
    provider = ScriptedProvider([[content_delta_event("done"), done_event()]])
    source = DurableSource(fails=True)
    loop, preparer, _, _ = build(tmp_path, provider, reminder=True, durable=source)

    failed = await drain(loop, AgentRunRequest("continue", NORMAL_AGENT_MODE))
    source.fails = False
    succeeded = await drain(loop, AgentRunRequest("retry", NORMAL_AGENT_MODE))

    assert failed[-1].payload["reason"] == StopReason.STREAM_ERROR.value
    assert succeeded[-1].payload["reason"] == StopReason.NATURAL.value
    assert len(provider.requests) == 1
    assert "超过 24 小时" in str(provider.requests[0].messages)
    assert not preparer.resume_reminder_pending


async def test_provider_attempt_consumes_resume_reminder_even_when_request_fails(tmp_path) -> None:
    first = ScriptedProvider([NetworkError("offline")])
    loop, preparer, _, _ = build(tmp_path, first, reminder=True)

    failed = await drain(loop, AgentRunRequest("continue", NORMAL_AGENT_MODE))
    second = ScriptedProvider([[content_delta_event("done"), done_event()]])
    loop.provider = second
    succeeded = await drain(loop, AgentRunRequest("retry", NORMAL_AGENT_MODE))

    assert failed[-1].payload["reason"] == StopReason.STREAM_ERROR.value
    assert succeeded[-1].payload["reason"] == StopReason.NATURAL.value
    assert "超过 24 小时" in str(first.requests[0].messages)
    assert "超过 24 小时" not in str(second.requests[0].messages)
    assert not preparer.resume_reminder_pending
