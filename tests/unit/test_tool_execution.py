from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from artcode.agent import AgentEventType, DO_MODE, NORMAL_AGENT_MODE, PLAN_MODE, ToolAccessPolicy
from artcode.permissions import PermissionState
from artcode.providers.tool_calls import ToolCall
from artcode.tools import (
    AllowedPathPolicy,
    DescriptorBackedTool,
    PreparedToolCall,
    ToolDescriptor,
    ToolEffect,
    ToolExecutionContext,
    ToolOrigin,
    ToolPreview,
    ToolRegistry,
    error_result,
    success_result,
)
from artcode.tools.execution import (
    ToolExecutionBlocked,
    ToolExecutionService,
    ToolSafety,
)
from artcode.tools.results import ToolResult

pytestmark = pytest.mark.ch10_5


class RecordingTool(DescriptorBackedTool):
    def __init__(
        self,
        name: str,
        effect: ToolEffect,
        *,
        origin: ToolOrigin = ToolOrigin.BUILTIN,
        prepare_value: Any = None,
        execute_value: Any = None,
        delay: float = 0,
    ) -> None:
        self.descriptor = ToolDescriptor(
            name,
            "recording tool",
            {"type": "object", "additionalProperties": True},
            effect,
            origin,
            origin is ToolOrigin.BUILTIN,
        )
        self.prepare_value = prepare_value
        self.execute_value = execute_value
        self.delay = delay
        self.prepared_arguments: list[dict[str, Any]] = []
        self.contexts = []
        self.started = False
        self.finished = False

    def prepare(self, arguments, context):
        self.prepared_arguments.append(arguments)
        self.contexts.append(context)
        if isinstance(self.prepare_value, BaseException):
            raise self.prepare_value
        if self.prepare_value is not None:
            return self.prepare_value
        return PreparedToolCall(
            self,
            arguments,
            ToolPreview(self.name, self.name, arguments.get("target", self.name), False),
        )

    async def execute(self, prepared, context):
        self.started = True
        self.contexts.append(context)
        if self.delay:
            await asyncio.sleep(self.delay)
        if isinstance(self.execute_value, BaseException):
            raise self.execute_value
        self.finished = True
        if self.execute_value is not None:
            return self.execute_value
        return success_result(self.name, f"{self.name} ok")


class DenyingPermissionService:
    def __init__(self, result: ToolResult) -> None:
        self.state = PermissionState()
        self.result = result

    async def authorize(self, descriptor, prepared, context):
        return self.result


def registry(*tools: RecordingTool) -> ToolRegistry:
    selected = ToolRegistry()
    selected.register_many(list(tools))
    return selected


def context(tmp_path: Path) -> ToolExecutionContext:
    return ToolExecutionContext(AllowedPathPolicy((tmp_path,)), default_cwd=tmp_path)


def call(name: str, arguments: str = "{}", identifier: str = "call") -> ToolCall:
    return ToolCall(identifier, name, arguments)


async def result_events(service: ToolExecutionService, plan, **kwargs):
    events = [event async for event in service.execute_plan(plan, **kwargs)]
    return [event for event in events if event.type is AgentEventType.TOOL_RESULT]


@pytest.mark.parametrize(
    ("effect", "origin", "expected"),
    [
        (ToolEffect.READ, ToolOrigin.BUILTIN, ToolSafety.READ_ONLY),
        (ToolEffect.WRITE, ToolOrigin.BUILTIN, ToolSafety.SIDE_EFFECT),
        (ToolEffect.SHELL, ToolOrigin.BUILTIN, ToolSafety.SIDE_EFFECT),
        (ToolEffect.EXTERNAL, ToolOrigin.MCP, ToolSafety.MCP_EXTERNAL),
    ],
    ids=("read", "write", "shell", "external"),
)
def test_descriptor_effect_selects_batch_safety(tmp_path, effect, origin, expected) -> None:
    tool = RecordingTool("selected", effect, origin=origin)
    service = ToolExecutionService(registry(tool), context(tmp_path))

    plan = service.build_plan([call(tool.name)], ToolAccessPolicy())

    assert plan.batches[0].safety is expected


@pytest.mark.parametrize(
    ("effects", "expected"),
    [
        ((ToolEffect.READ, ToolEffect.READ), ("read_only:2",)),
        ((ToolEffect.WRITE, ToolEffect.WRITE), ("side_effect:1", "side_effect:1")),
        ((ToolEffect.READ, ToolEffect.WRITE), ("read_only:1", "side_effect:1")),
        ((ToolEffect.WRITE, ToolEffect.READ), ("side_effect:1", "read_only:1")),
        ((ToolEffect.EXTERNAL, ToolEffect.EXTERNAL), ("mcp_external:2",)),
        ((ToolEffect.READ, ToolEffect.EXTERNAL, ToolEffect.READ), ("read_only:1", "mcp_external:1", "read_only:1")),
    ],
    ids=("reads-coalesce", "writes-serial", "read-write", "write-read", "external-coalesce", "origin-boundaries"),
)
def test_adjacent_effects_define_batch_boundaries(tmp_path, effects, expected) -> None:
    tools = [
        RecordingTool(
            f"tool_{index}",
            effect,
            origin=ToolOrigin.MCP if effect is ToolEffect.EXTERNAL else ToolOrigin.BUILTIN,
        )
        for index, effect in enumerate(effects)
    ]
    service = ToolExecutionService(registry(*tools), context(tmp_path))

    plan = service.build_plan(
        [call(tool.name, identifier=str(index)) for index, tool in enumerate(tools)],
        ToolAccessPolicy(),
    )

    assert tuple(f"{batch.safety.value}:{len(batch.tool_calls)}" for batch in plan.batches) == expected


@pytest.mark.parametrize(
    ("known", "policy", "code"),
    [
        (False, ToolAccessPolicy(), "tool_not_found"),
        (True, ToolAccessPolicy(frozenset({ToolEffect.READ})), "tool_not_allowed"),
    ],
    ids=("unknown", "mode-blocked"),
)
def test_plan_rejects_unexecutable_call(tmp_path, known, policy, code) -> None:
    tools = (RecordingTool("write", ToolEffect.WRITE),) if known else ()
    service = ToolExecutionService(registry(*tools), context(tmp_path))

    result = service.build_plan([call("write" if known else "missing")], policy)

    assert isinstance(result, ToolExecutionBlocked)
    assert result.result.error_code == code


@pytest.mark.parametrize(
    "arguments",
    ["{", "[]", "null", "1", '"text"', "true"],
    ids=("malformed", "array", "null", "number", "string", "boolean"),
)
async def test_non_object_arguments_return_structured_error(tmp_path, arguments) -> None:
    tool = RecordingTool("read", ToolEffect.READ)
    service = ToolExecutionService(registry(tool), context(tmp_path))
    plan = service.build_plan([call(tool.name, arguments)], ToolAccessPolicy())

    events = await result_events(service, plan)

    assert events[0].payload["result"].error_code == "invalid_arguments"
    assert not tool.started


@pytest.mark.parametrize(
    "prepared_result",
    [
        error_result("read", "preflight_denied", "no"),
        success_result("read", "already complete"),
    ],
    ids=("prepare-error-result", "prepare-success-result"),
)
async def test_prepare_tool_result_short_circuits_execution(tmp_path, prepared_result) -> None:
    tool = RecordingTool("read", ToolEffect.READ, prepare_value=prepared_result)
    service = ToolExecutionService(registry(tool), context(tmp_path))
    plan = service.build_plan([call(tool.name)], ToolAccessPolicy())

    events = await result_events(service, plan)

    assert events[0].payload["result"] is prepared_result
    assert not tool.started


@pytest.mark.parametrize("exception", [ValueError("bad"), RuntimeError("broken")], ids=("value", "runtime"))
async def test_prepare_exception_is_normalized(tmp_path, exception) -> None:
    tool = RecordingTool("read", ToolEffect.READ, prepare_value=exception)
    service = ToolExecutionService(registry(tool), context(tmp_path))
    plan = service.build_plan([call(tool.name)], ToolAccessPolicy())

    events = await result_events(service, plan)

    assert events[0].payload["result"].error_code == "tool_prepare_error"


@pytest.mark.parametrize("value", [object(), True], ids=("object", "boolean"))
async def test_invalid_prepare_return_is_normalized(tmp_path, value) -> None:
    tool = RecordingTool("read", ToolEffect.READ, prepare_value=value)
    service = ToolExecutionService(registry(tool), context(tmp_path))
    plan = service.build_plan([call(tool.name)], ToolAccessPolicy())

    events = await result_events(service, plan)

    assert events[0].payload["result"].error_code == "tool_prepare_error"


@pytest.mark.parametrize(
    "exception",
    [ValueError("bad"), RuntimeError("broken"), OSError("disk")],
    ids=("value", "runtime", "os"),
)
async def test_execute_exception_is_normalized(tmp_path, exception) -> None:
    tool = RecordingTool("read", ToolEffect.READ, execute_value=exception)
    service = ToolExecutionService(registry(tool), context(tmp_path))
    plan = service.build_plan([call(tool.name)], ToolAccessPolicy())

    events = await result_events(service, plan)

    assert events[0].payload["result"].error_code == "tool_execution_error"


@pytest.mark.parametrize("value", [object(), True, {"ok": True}], ids=("object", "boolean", "mapping"))
async def test_invalid_execute_return_is_normalized(tmp_path, value) -> None:
    tool = RecordingTool("read", ToolEffect.READ, execute_value=value)
    service = ToolExecutionService(registry(tool), context(tmp_path))
    plan = service.build_plan([call(tool.name)], ToolAccessPolicy())

    events = await result_events(service, plan)

    assert events[0].payload["result"].error_code == "tool_execution_error"


async def test_mode_and_legacy_plan_flag_are_mutually_exclusive(tmp_path) -> None:
    tool = RecordingTool("read", ToolEffect.READ)
    service = ToolExecutionService(registry(tool), context(tmp_path))
    plan = service.build_plan([call(tool.name)], ToolAccessPolicy())

    with pytest.raises(ValueError, match="mode or plan_mode"):
        await anext(service.execute_plan(plan, mode=NORMAL_AGENT_MODE, plan_mode=False))


@pytest.mark.parametrize("mode", [NORMAL_AGENT_MODE, PLAN_MODE, DO_MODE], ids=("normal", "plan", "do"))
async def test_each_execution_builds_context_with_requested_mode(tmp_path, mode) -> None:
    tool = RecordingTool("read", ToolEffect.READ)
    state = PermissionState()
    service = ToolExecutionService(
        registry(tool),
        context(tmp_path),
        permission_state=state,
    )
    plan = service.build_plan([call(tool.name)], mode.tool_policy)

    await result_events(service, plan, mode=mode)

    assert tool.contexts[0].mode is mode
    assert tool.contexts[0].permission == state.snapshot()


async def test_side_effect_batches_execute_in_plan_order(tmp_path) -> None:
    first = RecordingTool("first", ToolEffect.WRITE)
    second = RecordingTool("second", ToolEffect.WRITE)
    service = ToolExecutionService(registry(first, second), context(tmp_path))
    plan = service.build_plan([call("first", identifier="1"), call("second", identifier="2")], ToolAccessPolicy())

    events = await result_events(service, plan)

    assert [event.payload["tool_call"].id for event in events] == ["1", "2"]
    assert first.finished and second.finished


async def test_read_batch_runs_concurrently_and_reports_call_order(tmp_path) -> None:
    slow = RecordingTool("slow", ToolEffect.READ, delay=0.02)
    fast = RecordingTool("fast", ToolEffect.READ)
    service = ToolExecutionService(registry(slow, fast), context(tmp_path))
    plan = service.build_plan([call("slow", identifier="1"), call("fast", identifier="2")], ToolAccessPolicy())

    events = await result_events(service, plan)

    assert [event.payload["tool_call"].id for event in events] == ["1", "2"]
    assert slow.finished and fast.finished


async def test_external_batch_runs_concurrently_and_reports_call_order(tmp_path) -> None:
    slow = RecordingTool("slow", ToolEffect.EXTERNAL, origin=ToolOrigin.MCP, delay=0.02)
    fast = RecordingTool("fast", ToolEffect.EXTERNAL, origin=ToolOrigin.MCP)

    class AllowMcp:
        async def request_mcp_approval(self, preview, plan_mode):
            return True

    service = ToolExecutionService(registry(slow, fast), context(tmp_path), approver=AllowMcp())
    plan = service.build_plan([call("slow", identifier="1"), call("fast", identifier="2")], ToolAccessPolicy())

    events = await result_events(service, plan)

    assert [event.payload["tool_call"].id for event in events] == ["1", "2"]


@pytest.mark.parametrize(
    "denial",
    [
        error_result("write", "permission_denied", "rule"),
        error_result("write", "user_denied", "user"),
    ],
    ids=("rule", "user"),
)
async def test_permission_denial_short_circuits_tool(tmp_path, denial) -> None:
    tool = RecordingTool("write", ToolEffect.WRITE)
    service = ToolExecutionService(
        registry(tool),
        context(tmp_path),
        DenyingPermissionService(denial),
    )
    plan = service.build_plan([call(tool.name)], ToolAccessPolicy())

    events = await result_events(service, plan)

    assert events[0].payload["result"] is denial
    assert not tool.started


def test_explicit_permission_service_rejects_legacy_permission_arguments(tmp_path) -> None:
    tool = RecordingTool("read", ToolEffect.READ)
    permission = DenyingPermissionService(error_result("read", "x", "x"))

    with pytest.raises(ValueError, match="cannot be combined"):
        ToolExecutionService(
            registry(tool),
            context(tmp_path),
            permission,
            permission_state=PermissionState(),
        )
