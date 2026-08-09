from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from typing import Protocol

from artcode.permissions import (
    ApprovalChoice,
    ApprovalRequest,
    PermissionAction,
    PermissionEngine,
    PermissionRequest,
    PermissionState,
    RuleWriter,
)
from artcode.providers.tool_calls import ToolCall
from artcode.tools import (
    PreparedToolCall,
    Tool,
    ToolDescriptor,
    ToolEffect,
    ToolExecutionContext,
    ToolOrigin,
    ToolRegistry,
    ToolResult,
    ToolRunContext,
    error_result,
)

from .events import AgentEvent, StopReason, tool_batch_started_event, tool_result_event
from .modes import AgentMode, NORMAL_AGENT_MODE, PLAN_MODE, ToolAccessPolicy


class ToolSafety(StrEnum):
    READ_ONLY = "read_only"
    SIDE_EFFECT = "side_effect"
    MCP_EXTERNAL = "mcp_external"


@dataclass(frozen=True)
class ToolExecutionBatch:
    index: int
    safety: ToolSafety
    tool_calls: tuple[ToolCall, ...]


@dataclass(frozen=True)
class ToolExecutionPlan:
    batches: tuple[ToolExecutionBatch, ...]


@dataclass(frozen=True)
class PreparedToolExecution:
    tool_call: ToolCall
    tool: Tool
    prepared: PreparedToolCall


@dataclass(frozen=True)
class ToolExecutionBlocked:
    tool_call: ToolCall
    result: ToolResult
    stop_reason: StopReason = StopReason.UNKNOWN_TOOL


class PermissionApprover(Protocol):
    async def request_approval(self, request: ApprovalRequest) -> ApprovalChoice:
        ...

    async def request_mcp_approval(self, preview, plan_mode: bool) -> bool:
        ...


class ToolBatchExecutor:
    def __init__(
        self,
        tool_registry: ToolRegistry,
        tool_context: ToolExecutionContext,
        permission_engine: PermissionEngine | None = None,
        permission_state: PermissionState | None = None,
        approver: PermissionApprover | None = None,
        rule_writer: RuleWriter | None = None,
    ) -> None:
        self.tool_registry = tool_registry
        self.tool_context = tool_context
        self.permission_engine = permission_engine
        self.permission_state = permission_state or PermissionState(
            shell_policy=tool_context.shell_policy
        )
        self.approver = approver
        self.rule_writer = rule_writer

    def build_plan(
        self,
        tool_calls: list[ToolCall],
        policy: ToolAccessPolicy,
    ) -> ToolExecutionPlan | ToolExecutionBlocked:
        for tool_call in tool_calls:
            descriptor = self.tool_registry.descriptor(tool_call.name)
            if descriptor is None:
                return ToolExecutionBlocked(
                    tool_call,
                    error_result(tool_call.name or "unknown_tool", "tool_not_found", f"未知工具：{tool_call.name}"),
                )
            if not policy.allows(descriptor):
                return ToolExecutionBlocked(
                    tool_call,
                    error_result(
                        tool_call.name,
                        "tool_not_allowed",
                        f"当前模式不允许调用工具：{tool_call.name}",
                    ),
                )

        batches: list[ToolExecutionBatch] = []
        current_read_only: list[ToolCall] = []
        current_mcp: list[ToolCall] = []

        def flush_read_only() -> None:
            if current_read_only:
                batches.append(
                    ToolExecutionBatch(
                        index=len(batches) + 1,
                        safety=ToolSafety.READ_ONLY,
                        tool_calls=tuple(current_read_only),
                    )
                )
                current_read_only.clear()

        def flush_mcp() -> None:
            if current_mcp:
                batches.append(
                    ToolExecutionBatch(len(batches) + 1, ToolSafety.MCP_EXTERNAL, tuple(current_mcp))
                )
                current_mcp.clear()

        for tool_call in tool_calls:
            descriptor = self.tool_registry.descriptor(tool_call.name)
            assert descriptor is not None
            safety = classify_tool(descriptor)
            if safety == ToolSafety.READ_ONLY:
                flush_mcp()
                current_read_only.append(tool_call)
            elif safety == ToolSafety.MCP_EXTERNAL:
                flush_read_only()
                current_mcp.append(tool_call)
            else:
                flush_read_only()
                flush_mcp()
                batches.append(
                    ToolExecutionBatch(
                        index=len(batches) + 1,
                        safety=ToolSafety.SIDE_EFFECT,
                        tool_calls=(tool_call,),
                    )
                )
        flush_read_only()
        flush_mcp()
        return ToolExecutionPlan(tuple(batches))

    async def execute_plan(
        self,
        plan: ToolExecutionPlan,
        *,
        mode: AgentMode | None = None,
        plan_mode: bool | None = None,
    ):
        if mode is not None and plan_mode is not None:
            raise ValueError("pass mode or plan_mode, not both")
        selected_mode = mode or (PLAN_MODE if plan_mode else NORMAL_AGENT_MODE)
        run_context = self.tool_context.to_run_context(selected_mode, self.permission_state)
        for batch in plan.batches:
            yield tool_batch_started_event(batch.index, batch.safety.value, len(batch.tool_calls))
            prepared_items: list[tuple[ToolCall, PreparedToolCall] | tuple[ToolCall, ToolResult]] = []
            for tool_call in batch.tool_calls:
                prepared_items.append(
                    (tool_call, await self._prepare_and_authorize(tool_call, run_context))
                )
            if batch.safety in {ToolSafety.READ_ONLY, ToolSafety.MCP_EXTERNAL}:
                results = await asyncio.gather(
                    *(self._execute_prepared(item, run_context) for item in prepared_items)
                )
            else:
                results = []
                for item in prepared_items:
                    results.append(await self._execute_prepared(item, run_context))
            for (tool_call, _), result in zip(prepared_items, results):
                yield tool_result_event(tool_call, result)

    async def _prepare_and_authorize(
        self,
        tool_call: ToolCall,
        context: ToolRunContext,
    ) -> PreparedToolCall | ToolResult:
        parsed = self._parse_arguments(tool_call)
        if isinstance(parsed, ToolResult):
            return parsed

        tool = self.tool_registry.get(tool_call.name)
        if tool is None:
            return error_result(tool_call.name or "unknown_tool", "tool_not_found", f"未知工具：{tool_call.name}")

        prepared = tool.prepare(parsed, context)
        if isinstance(prepared, ToolResult):
            return prepared

        if tool.descriptor.origin is ToolOrigin.MCP:
            if self.approver is None:
                return error_result(tool_call.name, "permission_required", "MCP 工具需要人工确认，但审批器不可用。")
            allowed = await self.approver.request_mcp_approval(
                prepared.preview,
                context.mode == PLAN_MODE,
            )
            if not allowed:
                return error_result(tool_call.name, "user_denied", "用户拒绝执行该 MCP 工具。")
            return prepared

        if self.permission_engine is not None:
            descriptor = tool.descriptor
            try:
                decision = self.permission_engine.decide(
                    PermissionRequest(
                        tool_name=prepared.preview.tool_name,
                        target=_permission_target(prepared),
                        workspace=context.default_cwd or context.path_policy.allowed_roots[0],
                        plan_mode=context.mode == PLAN_MODE,
                        effect=descriptor.effect.value,
                        rule_configurable=descriptor.rule_configurable,
                    ),
                    context.permission,
                )
            except Exception as exc:
                return error_result(tool_call.name, "permission_rule_error", str(exc))
            if decision.action is PermissionAction.DENY:
                return error_result(
                    tool_call.name,
                    "permission_denied",
                    decision.reason,
                )
            if decision.action is PermissionAction.ASK:
                if self.approver is None:
                    return error_result(tool_call.name, "permission_required", "权限需要人工确认，但审批器不可用。")
                choice = await self.approver.request_approval(
                    ApprovalRequest(
                        tool_name=tool_call.name,
                        target=_permission_target(prepared),
                        workspace=context.default_cwd or context.path_policy.allowed_roots[0],
                        permission_mode=context.permission.mode,
                        shell_policy=context.permission.shell_policy,
                        source=decision.reason,
                    )
                )
                if choice in {ApprovalChoice.ALLOW_ALWAYS, ApprovalChoice.DENY_ALWAYS}:
                    if self.rule_writer is None:
                        return error_result(tool_call.name, "permission_rule_error", "本地规则写入器不可用。")
                    action = (
                        PermissionAction.ALLOW
                        if choice is ApprovalChoice.ALLOW_ALWAYS
                        else PermissionAction.DENY
                    )
                    try:
                        self.rule_writer.write_exact(
                            _exact_match(tool_call.name, _permission_target(prepared)),
                            action,
                        )
                    except Exception as exc:
                        return error_result(tool_call.name, "permission_rule_error", str(exc))
                if choice in {ApprovalChoice.DENY_ONCE, ApprovalChoice.DENY_ALWAYS}:
                    return error_result(tool_call.name, "user_denied", "用户拒绝执行该工具。")
        return prepared

    async def _execute_prepared(
        self,
        item: tuple[ToolCall, PreparedToolCall] | tuple[ToolCall, ToolResult],
        context: ToolRunContext,
    ) -> ToolResult:
        _tool_call, prepared = item
        if isinstance(prepared, ToolResult):
            return prepared
        return await prepared.tool.execute(prepared, context)

    def _parse_arguments(self, tool_call: ToolCall) -> dict[str, Any] | ToolResult:
        try:
            parsed = json.loads(tool_call.arguments_json or "{}")
        except json.JSONDecodeError as exc:
            return error_result(tool_call.name or "unknown_tool", "invalid_arguments", f"工具参数不是合法 JSON：{exc}")
        if not isinstance(parsed, dict):
            return error_result(tool_call.name or "unknown_tool", "invalid_arguments", "工具参数 JSON 必须是对象。")
        return parsed


def classify_tool(descriptor: ToolDescriptor) -> ToolSafety:
    if descriptor.effect is ToolEffect.READ:
        return ToolSafety.READ_ONLY
    if descriptor.effect is ToolEffect.EXTERNAL:
        return ToolSafety.MCP_EXTERNAL
    return ToolSafety.SIDE_EFFECT


def _permission_target(prepared: PreparedToolCall) -> str:
    if prepared.preview.tool_name == "run_command":
        return str(prepared.arguments["command"]).strip()
    return prepared.preview.target


def _exact_match(tool_name: str, target: str) -> str:
    escaped = (
        target.replace("\\", "\\\\")
        .replace("*", "\\*")
        .replace("?", "\\?")
        .replace("[", "\\[")
    )
    return f"{tool_name}({escaped})"
