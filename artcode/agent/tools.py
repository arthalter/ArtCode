from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from artcode.providers.tool_calls import ToolCall
from artcode.tools import PreparedToolCall, Tool, ToolExecutionContext, ToolRegistry, ToolResult, error_result

from .events import AgentEvent, StopReason, tool_batch_started_event, tool_result_event
from .modes import ToolAccessPolicy


class ToolSafety(StrEnum):
    READ_ONLY = "read_only"
    SIDE_EFFECT = "side_effect"


READ_ONLY_TOOLS = frozenset({"read_file", "find_files", "search_text"})
SIDE_EFFECT_TOOLS = frozenset({"write_file", "edit_file", "run_command"})


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


class ToolBatchExecutor:
    def __init__(
        self,
        tool_registry: ToolRegistry,
        tool_context: ToolExecutionContext,
    ) -> None:
        self.tool_registry = tool_registry
        self.tool_context = tool_context

    def build_plan(
        self,
        tool_calls: list[ToolCall],
        policy: ToolAccessPolicy,
    ) -> ToolExecutionPlan | ToolExecutionBlocked:
        for tool_call in tool_calls:
            if self.tool_registry.get(tool_call.name) is None:
                return ToolExecutionBlocked(
                    tool_call,
                    error_result(tool_call.name or "unknown_tool", "tool_not_found", f"未知工具：{tool_call.name}"),
                )
            if not policy.allows(tool_call.name):
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

        for tool_call in tool_calls:
            safety = classify_tool(tool_call.name)
            if safety == ToolSafety.READ_ONLY:
                current_read_only.append(tool_call)
            else:
                flush_read_only()
                batches.append(
                    ToolExecutionBatch(
                        index=len(batches) + 1,
                        safety=ToolSafety.SIDE_EFFECT,
                        tool_calls=(tool_call,),
                    )
                )
        flush_read_only()
        return ToolExecutionPlan(tuple(batches))

    async def execute_plan(self, plan: ToolExecutionPlan):
        for batch in plan.batches:
            yield tool_batch_started_event(batch.index, batch.safety.value, len(batch.tool_calls))
            if batch.safety == ToolSafety.READ_ONLY:
                results = await asyncio.gather(*(self._execute_one(tool_call) for tool_call in batch.tool_calls))
                for tool_call, result in zip(batch.tool_calls, results):
                    yield tool_result_event(tool_call, result)
            else:
                for tool_call in batch.tool_calls:
                    result = await self._execute_one(tool_call)
                    yield tool_result_event(tool_call, result)

    async def _execute_one(self, tool_call: ToolCall) -> ToolResult:
        parsed = self._parse_arguments(tool_call)
        if isinstance(parsed, ToolResult):
            return parsed

        tool = self.tool_registry.get(tool_call.name)
        if tool is None:
            return error_result(tool_call.name or "unknown_tool", "tool_not_found", f"未知工具：{tool_call.name}")

        prepared = tool.prepare(parsed, self.tool_context)
        if isinstance(prepared, ToolResult):
            return prepared

        return await tool.execute(prepared, self.tool_context)

    def _parse_arguments(self, tool_call: ToolCall) -> dict[str, Any] | ToolResult:
        try:
            parsed = json.loads(tool_call.arguments_json or "{}")
        except json.JSONDecodeError as exc:
            return error_result(tool_call.name or "unknown_tool", "invalid_arguments", f"工具参数不是合法 JSON：{exc}")
        if not isinstance(parsed, dict):
            return error_result(tool_call.name or "unknown_tool", "invalid_arguments", "工具参数 JSON 必须是对象。")
        return parsed


def classify_tool(tool_name: str) -> ToolSafety:
    if tool_name in READ_ONLY_TOOLS:
        return ToolSafety.READ_ONLY
    return ToolSafety.SIDE_EFFECT
