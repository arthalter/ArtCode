from __future__ import annotations

from pathlib import Path

from artcode.agent import NORMAL_AGENT_MODE
from artcode.permissions import PermissionMode, PermissionState
from artcode.permissions.service import PermissionService
from artcode.subagents.permissions import SubagentPermissionService
from artcode.tools import (
    DescriptorBackedTool,
    PreparedToolCall,
    ToolDescriptor,
    ToolEffect,
    ToolEnvironment,
    ToolOrigin,
    ToolPreview,
    ToolRunContext,
    success_result,
)


class _CountingMcpTool(DescriptorBackedTool):
    """An MCP-shaped tool whose implementation counts executions."""

    descriptor = ToolDescriptor(
        name="mcp_weather",
        description="模拟 MCP 工具",
        parameters_schema={"type": "object", "properties": {}, "additionalProperties": False},
        effect=ToolEffect.EXTERNAL,
        origin=ToolOrigin.MCP,
        rule_configurable=False,
    )

    def __init__(self) -> None:
        self.calls = 0

    def prepare(self, arguments: dict, context: ToolRunContext):
        return PreparedToolCall(
            self,
            arguments,
            ToolPreview(self.name, "查询天气", "beijing"),
        )

    async def execute(self, prepared: PreparedToolCall, context: ToolRunContext):
        self.calls += 1
        return success_result(self.name, "已执行 MCP 工具。")


class _ParentApprover:
    """The parent approval port that confirms the MCP tool once."""

    def __init__(self) -> None:
        self.mcp_approvals = 0

    async def request_approval(self, request):
        return __import__("artcode.permissions").ApprovalChoice.ALLOW_ONCE

    async def request_mcp_approval(self, preview, plan_mode: bool) -> bool:
        self.mcp_approvals += 1
        return True


async def test_mcp_tool_auto_denied_in_subagent_even_after_parent_approval(
    tmp_path: Path,
) -> None:
    """D11: a child never reuses the parent's one-off MCP confirmation;
    forged calls reaching the permission layer are auto-denied and the MCP
    tool implementation is never invoked."""
    mcp_tool = _CountingMcpTool()
    state = PermissionState(mode=PermissionMode.EDIT)
    environment = ToolEnvironment.from_workspace(tmp_path)
    context = ToolRunContext(environment, NORMAL_AGENT_MODE, state.snapshot())
    prepared = mcp_tool.prepare({}, context)

    # Parent: the interactive approval port confirms the MCP call.
    parent_approver = _ParentApprover()
    parent = PermissionService(
        state, engine=None, approver=parent_approver
    )
    parent_result = await parent.authorize(mcp_tool.descriptor, prepared, context)
    assert parent_result is None  # allowed
    assert parent_approver.mcp_approvals == 1

    # Child: a fresh tracker with no approval port at all.
    child = SubagentPermissionService("task-deadbeef", state, engine=None, approver=None)
    child_result = await child.authorize(mcp_tool.descriptor, prepared, context)

    assert child_result is not None
    assert child_result.ok is False
    assert child_result.error_code == "approval_required_in_subagent"
    assert child.events[-1].decision == "auto_denied"
    assert child.events[-1].tool_name == "mcp_weather"
    # The parent approval is not inherited: the child still refuses and the
    # tool implementation never runs in the child's context.
    assert mcp_tool.calls == 0
