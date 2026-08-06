from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from artcode.agent import AgentEventType, ToolAccessPolicy
from artcode.agent.tools import ToolBatchExecutor, ToolExecutionBlocked, ToolSafety, classify_tool
from artcode.providers.tool_calls import ToolCall
from artcode.tools import AllowedPathPolicy, PreparedToolCall, ToolExecutionContext, ToolOrigin, ToolPreview, ToolRegistry
from artcode.tools.results import ToolResult, error_result, success_result


class FakeTool:
    description = "fake"
    parameters_schema = {"type": "object", "properties": {}, "additionalProperties": True}

    def __init__(self, name: str, delay: float = 0.0, result: ToolResult | None = None) -> None:
        self.name = name
        self.delay = delay
        self.result = result
        self.requires_confirmation = name not in {"read_file", "find_files", "search_text"}
        self.started: list[str] = []
        self.finished: list[str] = []

    def prepare(self, arguments: dict[str, Any], context: ToolExecutionContext) -> PreparedToolCall | ToolResult:
        if arguments.get("prepare_error"):
            return error_result(self.name, "prepare_error", "预检失败。")
        return PreparedToolCall(self, arguments, ToolPreview(self.name, self.name, self.name, self.requires_confirmation))

    async def execute(self, prepared: PreparedToolCall, context: ToolExecutionContext) -> ToolResult:
        self.started.append(self.name)
        if self.delay:
            await asyncio.sleep(self.delay)
        self.finished.append(self.name)
        return self.result or success_result(self.name, f"{self.name} ok")


class FakeMcpTool(FakeTool):
    origin = ToolOrigin.MCP


class FakeMcpApprover:
    def __init__(self, choices: list[bool]) -> None:
        self.choices = choices
        self.previews = []

    async def request_mcp_approval(self, preview) -> bool:
        self.previews.append(preview)
        return self.choices.pop(0)


def context_for(tmp_path: Path) -> ToolExecutionContext:
    return ToolExecutionContext(AllowedPathPolicy((tmp_path,)), default_cwd=tmp_path)


def registry_with(*tools: FakeTool) -> ToolRegistry:
    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool)
    return registry


def test_classifies_run_command_as_side_effect() -> None:
    assert classify_tool("read_file") == ToolSafety.READ_ONLY
    assert classify_tool("run_command") == ToolSafety.SIDE_EFFECT


def test_build_plan_groups_adjacent_read_only_tools(tmp_path) -> None:
    executor = ToolBatchExecutor(
        registry_with(FakeTool("read_file"), FakeTool("search_text"), FakeTool("write_file"), FakeTool("find_files")),
        context_for(tmp_path),
    )
    calls = [
        ToolCall("1", "read_file", "{}"),
        ToolCall("2", "search_text", "{}"),
        ToolCall("3", "write_file", "{}"),
        ToolCall("4", "find_files", "{}"),
    ]

    plan = executor.build_plan(calls, ToolAccessPolicy())

    assert [batch.safety for batch in plan.batches] == [
        ToolSafety.READ_ONLY,
        ToolSafety.SIDE_EFFECT,
        ToolSafety.READ_ONLY,
    ]
    assert [len(batch.tool_calls) for batch in plan.batches] == [2, 1, 1]


def test_build_plan_blocks_unknown_tool(tmp_path) -> None:
    executor = ToolBatchExecutor(registry_with(FakeTool("read_file")), context_for(tmp_path))

    result = executor.build_plan([ToolCall("1", "missing", "{}")], ToolAccessPolicy())

    assert isinstance(result, ToolExecutionBlocked)
    assert result.result.error_code == "tool_not_found"


def test_build_plan_blocks_disallowed_tool(tmp_path) -> None:
    executor = ToolBatchExecutor(registry_with(FakeTool("write_file")), context_for(tmp_path))

    result = executor.build_plan([ToolCall("1", "write_file", "{}")], ToolAccessPolicy(frozenset({"read_file"})))

    assert isinstance(result, ToolExecutionBlocked)
    assert result.result.error_code == "tool_not_allowed"


async def test_read_only_batch_runs_concurrently_but_yields_original_order(tmp_path) -> None:
    slow = FakeTool("read_file", delay=0.03)
    fast = FakeTool("search_text", delay=0.0)
    executor = ToolBatchExecutor(registry_with(slow, fast), context_for(tmp_path))
    plan = executor.build_plan(
        [ToolCall("1", "read_file", "{}"), ToolCall("2", "search_text", "{}")],
        ToolAccessPolicy(),
    )

    events = [event async for event in executor.execute_plan(plan)]

    result_events = [event for event in events if event.type == AgentEventType.TOOL_RESULT]
    assert [event.payload["tool_call"].id for event in result_events] == ["1", "2"]
    assert slow.started and fast.started


async def test_side_effect_batch_runs_serially(tmp_path) -> None:
    first = FakeTool("write_file")
    second = FakeTool("run_command")
    executor = ToolBatchExecutor(registry_with(first, second), context_for(tmp_path))
    plan = executor.build_plan(
        [ToolCall("1", "write_file", "{}"), ToolCall("2", "run_command", "{}")],
        ToolAccessPolicy(),
    )

    events = [event async for event in executor.execute_plan(plan)]

    assert [event.payload["tool_call"].id for event in events if event.type == AgentEventType.TOOL_RESULT] == ["1", "2"]


async def test_mcp_batch_asks_each_call_and_runs_approved_calls(tmp_path) -> None:
    first = FakeMcpTool("external_one")
    second = FakeMcpTool("external_two")
    approver = FakeMcpApprover([True, False])
    executor = ToolBatchExecutor(
        registry_with(first, second), context_for(tmp_path), approver=approver
    )
    plan = executor.build_plan(
        [ToolCall("1", first.name, "{}"), ToolCall("2", second.name, "{}")],
        ToolAccessPolicy(frozenset()),
    )

    events = [event async for event in executor.execute_plan(plan, plan_mode=True)]
    results = [event.payload["result"] for event in events if event.type == AgentEventType.TOOL_RESULT]

    assert plan.batches[0].safety is ToolSafety.MCP_EXTERNAL
    assert len(approver.previews) == 2
    assert first.started
    assert not second.started
    assert results[1].error_code == "user_denied"
