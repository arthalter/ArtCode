from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from artcode.permissions import PermissionEngine, PermissionState, RuleWriter
from artcode.permissions.service import ApprovalPort, PermissionService
from artcode.providers.tool_calls import ToolCall

from .base import (
    PreparedToolCall,
    ToolDescriptor,
    ToolEffect,
    ToolExecutionContext,
    ToolResult,
    ToolRunContext,
)
from .registry import ToolRegistry
from .results import error_result

if TYPE_CHECKING:
    from artcode.agent.events import AgentEvent, StopReason
    from artcode.agent.modes import AgentMode, ToolAccessPolicy


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
class ToolExecutionBlocked:
    tool_call: ToolCall
    result: ToolResult

    @property
    def stop_reason(self) -> StopReason:
        from artcode.agent.events import StopReason

        return StopReason.UNKNOWN_TOOL


class ToolExecutionService:
    def __init__(
        self,
        tool_registry: ToolRegistry,
        tool_context: ToolExecutionContext,
        permission_service: PermissionService | None = None,
        *,
        permission_engine: PermissionEngine | None = None,
        permission_state: PermissionState | None = None,
        approver: ApprovalPort | None = None,
        rule_writer: RuleWriter | None = None,
    ) -> None:
        if permission_service is not None and any(
            value is not None
            for value in (permission_engine, permission_state, approver, rule_writer)
        ):
            raise ValueError("permission_service cannot be combined with legacy permission arguments")
        state = permission_state or PermissionState(shell_policy=tool_context.shell_policy)
        self.tool_registry = tool_registry
        self.tool_context = tool_context
        self.permission_service = permission_service or PermissionService(
            state,
            engine=permission_engine,
            approver=approver,
            rule_writer=rule_writer,
        )

    def build_plan(
        self,
        tool_calls: Sequence[ToolCall],
        policy: ToolAccessPolicy,
    ) -> ToolExecutionPlan | ToolExecutionBlocked:
        for tool_call in tool_calls:
            descriptor = self.tool_registry.descriptor(tool_call.name)
            if descriptor is None:
                return ToolExecutionBlocked(
                    tool_call,
                    error_result(
                        tool_call.name or "unknown_tool",
                        "tool_not_found",
                        f"未知工具：{tool_call.name}",
                    ),
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
        current_read: list[ToolCall] = []
        current_external: list[ToolCall] = []

        def flush(calls: list[ToolCall], safety: ToolSafety) -> None:
            if calls:
                batches.append(ToolExecutionBatch(len(batches) + 1, safety, tuple(calls)))
                calls.clear()

        for tool_call in tool_calls:
            descriptor = self.tool_registry.descriptor(tool_call.name)
            assert descriptor is not None
            safety = classify_tool(descriptor)
            if safety is ToolSafety.READ_ONLY:
                flush(current_external, ToolSafety.MCP_EXTERNAL)
                current_read.append(tool_call)
            elif safety is ToolSafety.MCP_EXTERNAL:
                flush(current_read, ToolSafety.READ_ONLY)
                current_external.append(tool_call)
            else:
                flush(current_read, ToolSafety.READ_ONLY)
                flush(current_external, ToolSafety.MCP_EXTERNAL)
                batches.append(
                    ToolExecutionBatch(
                        len(batches) + 1,
                        ToolSafety.SIDE_EFFECT,
                        (tool_call,),
                    )
                )
        flush(current_read, ToolSafety.READ_ONLY)
        flush(current_external, ToolSafety.MCP_EXTERNAL)
        return ToolExecutionPlan(tuple(batches))

    async def execute_plan(
        self,
        plan: ToolExecutionPlan,
        *,
        mode: AgentMode | None = None,
        plan_mode: bool | None = None,
    ) -> AsyncIterator[AgentEvent]:
        from artcode.agent.events import tool_batch_started_event, tool_result_event
        from artcode.agent.modes import NORMAL_AGENT_MODE, PLAN_MODE

        if mode is not None and plan_mode is not None:
            raise ValueError("pass mode or plan_mode, not both")
        selected_mode = mode or (PLAN_MODE if plan_mode else NORMAL_AGENT_MODE)
        for batch in plan.batches:
            context = self.tool_context.to_run_context(
                selected_mode,
                self.permission_service.state,
            )
            yield tool_batch_started_event(batch.index, batch.safety.value, len(batch.tool_calls))
            prepared = [
                (tool_call, await self._prepare_and_authorize(tool_call, context))
                for tool_call in batch.tool_calls
            ]
            if batch.safety in {ToolSafety.READ_ONLY, ToolSafety.MCP_EXTERNAL}:
                results = await asyncio.gather(
                    *(self._execute_prepared(item, context) for item in prepared)
                )
            else:
                results = []
                for item in prepared:
                    results.append(await self._execute_prepared(item, context))
            for (tool_call, _), result in zip(prepared, results):
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
            return error_result(
                tool_call.name or "unknown_tool",
                "tool_not_found",
                f"未知工具：{tool_call.name}",
            )
        try:
            prepared = tool.prepare(parsed, context)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return error_result(tool_call.name, "tool_prepare_error", str(exc))
        if isinstance(prepared, ToolResult):
            return prepared
        if not isinstance(prepared, PreparedToolCall):
            return error_result(
                tool_call.name,
                "tool_prepare_error",
                "工具 prepare 返回了非法结果。",
            )
        denied = await self.permission_service.authorize(tool.descriptor, prepared, context)
        return denied or prepared

    async def _execute_prepared(
        self,
        item: tuple[ToolCall, PreparedToolCall] | tuple[ToolCall, ToolResult],
        context: ToolRunContext,
    ) -> ToolResult:
        tool_call, prepared = item
        if isinstance(prepared, ToolResult):
            return prepared
        try:
            result = await prepared.tool.execute(prepared, context)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return error_result(tool_call.name, "tool_execution_error", str(exc))
        if not isinstance(result, ToolResult):
            return error_result(
                tool_call.name,
                "tool_execution_error",
                "工具 execute 返回了非法结果。",
            )
        return result

    @staticmethod
    def _parse_arguments(tool_call: ToolCall) -> dict[str, Any] | ToolResult:
        try:
            parsed = json.loads(tool_call.arguments_json or "{}")
        except json.JSONDecodeError as exc:
            return error_result(
                tool_call.name or "unknown_tool",
                "invalid_arguments",
                f"工具参数不是合法 JSON：{exc}",
            )
        if not isinstance(parsed, dict):
            return error_result(
                tool_call.name or "unknown_tool",
                "invalid_arguments",
                "工具参数 JSON 必须是对象。",
            )
        return parsed


def classify_tool(descriptor: ToolDescriptor) -> ToolSafety:
    if descriptor.effect is ToolEffect.READ:
        return ToolSafety.READ_ONLY
    if descriptor.effect is ToolEffect.EXTERNAL:
        return ToolSafety.MCP_EXTERNAL
    return ToolSafety.SIDE_EFFECT


# Transitional name retained until T14 removes the old Agent tools module.
ToolBatchExecutor = ToolExecutionService
