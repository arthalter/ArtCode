from __future__ import annotations

import asyncio

import pytest

from artcode.agent import AgentEventType, NORMAL_AGENT_MODE, ToolAccessPolicy
from artcode.permissions import ApprovalChoice, PermissionAction, PermissionState
from artcode.permissions.service import PermissionService
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

pytestmark = [pytest.mark.ch10_5, pytest.mark.fault]


class FaultTool(DescriptorBackedTool):
    def __init__(self, name: str, *, prepare_cancel=False, execute_cancel=False, execute_error=False):
        self.descriptor = ToolDescriptor(name, "fault tool", {"type": "object"}, ToolEffect.READ)
        self.prepare_cancel = prepare_cancel
        self.execute_cancel = execute_cancel
        self.execute_error = execute_error

    def prepare(self, arguments, context):
        if self.prepare_cancel:
            raise asyncio.CancelledError
        return PreparedToolCall(self, arguments, ToolPreview(self.name, self.name, self.name))

    async def execute(self, prepared, context):
        if self.execute_cancel:
            raise asyncio.CancelledError
        if self.execute_error:
            raise RuntimeError("injected execute failure")
        return success_result(self.name, f"{self.name} ok")


def service(tmp_path, *tools) -> ToolExecutionService:
    registry = ToolRegistry()
    registry.register_many(list(tools))
    return ToolExecutionService(
        registry,
        ToolEnvironment.from_workspace(tmp_path),
        PermissionService(PermissionState()),
    )


async def consume(selected: ToolExecutionService, names: list[str]):
    plan = selected.build_plan(
        [ToolCall(str(index), name, "{}") for index, name in enumerate(names)],
        ToolAccessPolicy(),
    )
    return [event async for event in selected.execute_plan(plan, mode=NORMAL_AGENT_MODE)]


async def test_prepare_cancellation_propagates_to_agent_boundary(tmp_path) -> None:
    selected = service(tmp_path, FaultTool("cancel", prepare_cancel=True))

    with pytest.raises(asyncio.CancelledError):
        await consume(selected, ["cancel"])


async def test_execute_cancellation_propagates_to_agent_boundary(tmp_path) -> None:
    selected = service(tmp_path, FaultTool("cancel", execute_cancel=True))

    with pytest.raises(asyncio.CancelledError):
        await consume(selected, ["cancel"])


async def test_one_read_failure_keeps_other_batch_results_in_call_order(tmp_path) -> None:
    selected = service(
        tmp_path,
        FaultTool("first"),
        FaultTool("broken", execute_error=True),
        FaultTool("third"),
    )

    events = await consume(selected, ["first", "broken", "third"])
    results = [event.payload["result"] for event in events if event.type is AgentEventType.TOOL_RESULT]

    assert [result.tool_name for result in results] == ["first", "broken", "third"]
    assert [result.ok for result in results] == [True, False, True]
    assert results[1].error_code == "tool_execution_error"


async def test_rule_write_failure_is_atomic_and_returns_structured_error(tmp_path, monkeypatch) -> None:
    class AskEngine:
        def decide(self, request, state):
            from artcode.permissions import PermissionDecision, RuleSource

            return PermissionDecision(PermissionAction.ASK, RuleSource.MODE, "fixture")

    class AlwaysApprover:
        async def request_approval(self, request):
            return ApprovalChoice.ALLOW_ALWAYS

    class FailingWriter:
        def write_exact(self, match, action):
            raise OSError("injected disk failure")

    tool = FaultTool("read")
    registry = ToolRegistry()
    registry.register(tool)
    permission = PermissionService(
        PermissionState(),
        engine=AskEngine(),
        approver=AlwaysApprover(),
        rule_writer=FailingWriter(),
    )
    selected = ToolExecutionService(
        registry,
        ToolEnvironment.from_workspace(tmp_path),
        permission,
    )

    events = await consume(selected, ["read"])
    result = next(event.payload["result"] for event in events if event.type is AgentEventType.TOOL_RESULT)

    assert result.error_code == "permission_rule_error"
    assert not (tmp_path / "permissions.local.yml").exists()
