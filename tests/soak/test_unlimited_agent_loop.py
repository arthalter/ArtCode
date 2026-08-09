from __future__ import annotations

import pytest

from artcode.agent import AgentLoop, AgentRunRequest, NORMAL_AGENT_MODE, RequestPreparer, StopReason
from artcode.conversation import ConversationContext
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

pytestmark = [pytest.mark.ch10_5, pytest.mark.soak, pytest.mark.slow]


class ChainProvider:
    def __init__(self, tool_turns: int, *, final_text: bool = True) -> None:
        self.remaining = tool_turns
        self.final_text = final_text
        self.calls = 0

    async def stream(self, request):
        self.calls += 1
        if self.remaining:
            index = self.remaining
            self.remaining -= 1
            yield tool_calls_event([ToolCall(f"call-{index}", "read_file", "{}")])
            yield done_event("tool_calls")
            return
        if self.final_text:
            yield content_delta_event("done")
            yield done_event("stop")


class FastTool(DescriptorBackedTool):
    descriptor = ToolDescriptor(
        "read_file",
        "read",
        {"type": "object", "properties": {}},
        ToolEffect.READ,
    )

    def __init__(self) -> None:
        self.calls = 0

    def prepare(self, arguments, context):
        return PreparedToolCall(self, arguments, ToolPreview(self.name, "read", "read"))

    async def execute(self, prepared, context):
        self.calls += 1
        return success_result(self.name, "ok")


def build(tmp_path, provider, *, reminder=False):
    conversation = ConversationContext()
    environment = ToolEnvironment.from_workspace(tmp_path)
    permission = PermissionState()
    registry = ToolRegistry()
    tool = FastTool()
    registry.register(tool)
    preparer = RequestPreparer(
        conversation,
        PromptRequestAssembler(),
        registry,
        environment,
        permission,
        resume_reminder_required=reminder,
    )
    return (
        AgentLoop(
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
        ),
        preparer,
        tool,
    )


@pytest.mark.parametrize("turns", [13, 25, 50], ids=("past-old-limit", "medium", "long"))
async def test_long_tool_chains_complete_iteratively_without_a_default_limit(tmp_path, turns: int) -> None:
    provider = ChainProvider(turns)
    loop, _, tool = build(tmp_path, provider)

    events = [event async for event in loop.run(AgentRunRequest("continue", NORMAL_AGENT_MODE))]

    assert provider.calls == turns + 1
    assert tool.calls == turns
    assert events[-1].payload["reason"] == StopReason.NATURAL.value


async def test_thousand_previews_do_not_consume_or_duplicate_pending_state(tmp_path) -> None:
    provider = ChainProvider(0)
    loop, preparer, _ = build(tmp_path, provider, reminder=True)

    previews = [preparer.preview_request(NORMAL_AGENT_MODE) for _ in range(1_000)]
    events = [event async for event in loop.run(AgentRunRequest("continue", NORMAL_AGENT_MODE))]

    assert all(request.includes_resume_reminder for request in previews)
    assert provider.calls == 1
    assert not preparer.resume_reminder_pending
    assert events[-1].payload["reason"] == StopReason.NATURAL.value


async def test_large_explicit_limit_stops_exactly_without_recursive_summary(tmp_path) -> None:
    provider = ChainProvider(100, final_text=False)
    loop, _, tool = build(tmp_path, provider)

    events = [
        event
        async for event in loop.run(
            AgentRunRequest(
                "bounded",
                NORMAL_AGENT_MODE,
                max_iterations=100,
                final_summary_on_abnormal_stop=False,
            )
        )
    ]

    assert provider.calls == 100
    assert tool.calls == 100
    assert events[-1].payload["reason"] == StopReason.ITERATION_LIMIT.value
