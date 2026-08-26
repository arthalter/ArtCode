from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from artcode.agent import NORMAL_AGENT_MODE
from artcode.background import BackgroundTaskManager, BackgroundTaskStatus
from artcode.conversation import ConversationContext
from artcode.permissions import PermissionState
from artcode.subagents.models import (
    AgentCreateRequest,
    AgentKind,
    SubagentResult,
    SubagentStopReason,
    UsageTotals,
)
from artcode.providers.events import TokenUsage
from artcode.subagents.tool import AgentTool
from artcode.tools import ToolEnvironment, ToolResult, ToolRunContext


def _context(tmp_path, *, child: bool = False) -> ToolRunContext:
    environment = ToolEnvironment.from_workspace(tmp_path)
    if child:
        environment = replace(environment, is_subagent=True, agent_id="task-deadbeef")
    return ToolRunContext(
        environment, NORMAL_AGENT_MODE, PermissionState().snapshot()
    )


def _tool() -> AgentTool:
    return AgentTool(None, None, None, ConversationContext())  # type: ignore[arg-type]


def test_agent_tool_has_one_stable_four_field_schema() -> None:
    descriptor = AgentTool.descriptor

    assert descriptor.name == "agent"
    assert set(descriptor.parameters_schema["properties"]) == {
        "type",
        "task",
        "role",
        "background",
    }
    assert descriptor.parameters_schema["required"] == ["type", "task"]
    assert descriptor.parameters_schema["additionalProperties"] is False
    assert descriptor.subagent_allowed is False


@pytest.mark.parametrize(
    "arguments",
    (
        {},
        {"type": "missing", "task": "x"},
        {"type": "definition", "task": "x"},
        {"type": "definition", "task": " ", "role": "reader"},
        {"type": "definition", "task": "x" * 20_001, "role": "reader"},
        {"type": "definition", "task": "x", "role": "reader", "model": "x"},
        {"type": "fork", "task": "x", "background": False},
    ),
)
def test_agent_tool_rejects_invalid_argument_matrix(tmp_path, arguments) -> None:
    result = _tool().prepare(arguments, _context(tmp_path))

    assert isinstance(result, ToolResult)
    assert result.ok is False
    assert result.error_code == "invalid_arguments"


def test_agent_tool_normalizes_definition_and_fork_defaults(tmp_path) -> None:
    tool = _tool()

    definition = tool.prepare(
        {"type": "definition", "task": "  检查  ", "role": "reader"},
        _context(tmp_path),
    )
    fork = tool.prepare(
        {"type": "fork", "task": "继承事实"}, _context(tmp_path)
    )

    assert definition.arguments["request"] == AgentCreateRequest(
        AgentKind.DEFINITION, "检查", "reader", False
    )
    assert fork.arguments["request"] == AgentCreateRequest(
        AgentKind.FORK, "继承事实", None, True
    )


def test_nested_agent_source_is_rejected_before_task_creation(tmp_path) -> None:
    result = _tool().prepare(
        {"type": "fork", "task": "伪造委派"}, _context(tmp_path, child=True)
    )

    assert isinstance(result, ToolResult)
    assert result.error_code == "nested_subagent_forbidden"


async def test_task_ids_retry_collisions_and_remain_unique() -> None:
    suffixes = iter(("deadbeef", "deadbeef", "cafebabe"))
    manager = BackgroundTaskManager(id_factory=lambda: next(suffixes))

    async def run(task_id: str) -> SubagentResult:
        return SubagentResult(task_id, SubagentStopReason.NATURAL, "done", 1)

    request = AgentCreateRequest(AgentKind.DEFINITION, "x", "reader", True)
    first = manager.submit(request, run, worktree_required=False)
    second = manager.submit(request, run, worktree_required=False)
    await manager.wait_all()

    assert (first.task_id, second.task_id) == (
        "task-deadbeef",
        "task-cafebabe",
    )


async def test_manual_foreground_promotion_keeps_same_runner_alive() -> None:
    gate = asyncio.Event()
    starts: list[str] = []
    manager = BackgroundTaskManager(id_factory=lambda: "1234abcd")

    async def run(task_id: str) -> SubagentResult:
        starts.append(task_id)
        await gate.wait()
        return SubagentResult(task_id, SubagentStopReason.NATURAL, "done", 2)

    request = AgentCreateRequest(AgentKind.DEFINITION, "x", "reader", False)
    summary = manager.submit(request, run, worktree_required=False)
    waiter = asyncio.create_task(manager.wait_foreground(summary.task_id, 60))
    await asyncio.sleep(0)

    assert manager.promote_current_foreground() == summary.task_id
    promoted = await waiter
    assert promoted is not None
    assert promoted.status is BackgroundTaskStatus.RUNNING
    assert promoted.background is True
    assert starts == [summary.task_id]

    gate.set()
    completed = await manager.wait(summary.task_id)
    assert completed is not None
    assert completed.status is BackgroundTaskStatus.COMPLETED
    assert starts == [summary.task_id]


def test_usage_totals_sum_real_fields_and_keep_mixed_missing_values_unknown() -> None:
    totals = UsageTotals.empty()
    totals = totals.add(
        TokenUsage(
            prompt_tokens=10,
            completion_tokens=None,
            total_tokens=20,
            cached_tokens=3,
            cache_miss_tokens=None,
        )
    )
    totals = totals.add(
        TokenUsage(
            prompt_tokens=5,
            completion_tokens=2,
            total_tokens=7,
            cached_tokens=None,
            cache_miss_tokens=5,
        )
    )

    assert totals.to_dict() == {
        "prompt_tokens": 15,
        "completion_tokens": None,
        "total_tokens": 27,
        "cached_tokens": None,
        "cache_miss_tokens": None,
    }
    assert totals.reported_rounds == 2
