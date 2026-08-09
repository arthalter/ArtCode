from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from artcode.agent import AgentEventType, PLAN_MODE, ToolAccessPolicy
from artcode.permissions import (
    ApprovalChoice,
    PermissionAction,
    PermissionEngine,
    PermissionState,
    RuleLoader,
    RulePaths,
    RuleWriter,
)
from artcode.permissions.service import PermissionService
from artcode.providers.tool_calls import ToolCall
from artcode.security import DangerousCommandValidator
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
    create_default_tool_registry,
    success_result,
)
from artcode.tools.execution import ToolExecutionBlocked, ToolExecutionService, ToolSafety

pytestmark = pytest.mark.ch10_5


class ChoiceApprover:
    def __init__(self, choice=ApprovalChoice.ALLOW_ONCE, mcp=True) -> None:
        self.choice = choice
        self.mcp = mcp
        self.requests = []

    async def request_approval(self, request):
        self.requests.append(request)
        return self.choice

    async def request_mcp_approval(self, preview, plan_mode):
        self.requests.append((preview, plan_mode))
        return self.mcp


class IntegrationTool(DescriptorBackedTool):
    def __init__(
        self,
        name: str,
        effect: ToolEffect,
        *,
        origin: ToolOrigin = ToolOrigin.BUILTIN,
        fail: bool = False,
    ) -> None:
        self.descriptor = ToolDescriptor(
            name,
            "integration tool",
            {"type": "object", "additionalProperties": True},
            effect,
            origin,
            origin is ToolOrigin.BUILTIN,
        )
        self.fail = fail
        self.executed = False

    def prepare(self, arguments, context):
        target = arguments.get("target", self.name)
        return PreparedToolCall(self, arguments, ToolPreview(self.name, self.name, target, True))

    async def execute(self, prepared, context):
        self.executed = True
        if self.fail:
            raise RuntimeError(f"{self.name} failed")
        return success_result(self.name, f"{self.name} ok", prepared.arguments.get("content", ""))


def execution_context(tmp_path: Path) -> ToolExecutionContext:
    return ToolExecutionContext(AllowedPathPolicy((tmp_path,)), default_cwd=tmp_path)


def engine(tmp_path: Path, *, allowed_names=None):
    loader = RuleLoader(
        RulePaths(tmp_path / "user.yml", tmp_path / "project.yml", tmp_path / "local.yml"),
        allowed_tool_names=allowed_names,
    )
    return PermissionEngine(loader, DangerousCommandValidator.load()), loader


async def execute(service: ToolExecutionService, calls: list[ToolCall], policy=None, mode=None):
    plan = service.build_plan(calls, policy or ToolAccessPolicy())
    if isinstance(plan, ToolExecutionBlocked):
        return plan, []
    events = [event async for event in service.execute_plan(plan, mode=mode)]
    results = [event.payload["result"] for event in events if event.type is AgentEventType.TOOL_RESULT]
    return plan, results


@pytest.mark.parametrize(
    ("tool_name", "arguments", "expected"),
    [
        ("read_file", {"path": "note.txt"}, "needle"),
        ("find_files", {"pattern": "*.txt"}, "note.txt"),
        ("search_text", {"query": "needle"}, "needle"),
    ],
    ids=("read", "find", "search"),
)
async def test_default_read_tools_flow_through_service(tmp_path, tool_name, arguments, expected) -> None:
    (tmp_path / "note.txt").write_text("needle\n", encoding="utf-8")
    service = ToolExecutionService(create_default_tool_registry(), execution_context(tmp_path))

    _plan, results = await execute(
        service,
        [ToolCall("one", tool_name, json.dumps(arguments))],
    )

    assert results[0].ok
    assert expected in results[0].content


@pytest.mark.parametrize(
    ("choice", "written", "persisted"),
    [
        (ApprovalChoice.ALLOW_ONCE, True, False),
        (ApprovalChoice.DENY_ONCE, False, False),
        (ApprovalChoice.ALLOW_ALWAYS, True, True),
        (ApprovalChoice.DENY_ALWAYS, False, True),
    ],
    ids=("allow-once", "deny-once", "allow-always", "deny-always"),
)
async def test_write_file_preserves_all_four_approval_choices(tmp_path, choice, written, persisted) -> None:
    permission_engine, loader = engine(tmp_path)
    approver = ChoiceApprover(choice)
    permission = PermissionService(
        PermissionState(),
        engine=permission_engine,
        approver=approver,
        rule_writer=RuleWriter(loader),
    )
    service = ToolExecutionService(create_default_tool_registry(), execution_context(tmp_path), permission)

    _plan, results = await execute(
        service,
        [ToolCall("one", "write_file", '{"path":"note.txt","content":"value"}')],
    )

    assert (tmp_path / "note.txt").exists() is written
    assert results[0].ok is written
    assert loader.paths.local.exists() is persisted


@pytest.mark.parametrize(
    ("effect", "origin", "blocked"),
    [
        (ToolEffect.WRITE, ToolOrigin.BUILTIN, True),
        (ToolEffect.SHELL, ToolOrigin.BUILTIN, True),
        (ToolEffect.EXTERNAL, ToolOrigin.MCP, False),
    ],
    ids=("plan-write", "plan-shell", "plan-mcp"),
)
async def test_plan_policy_blocks_side_effects_but_confirms_mcp(tmp_path, effect, origin, blocked) -> None:
    tool = IntegrationTool("selected", effect, origin=origin)
    registry = ToolRegistry()
    registry.register(tool)
    approver = ChoiceApprover(mcp=True)
    service = ToolExecutionService(registry, execution_context(tmp_path), approver=approver)

    plan, results = await execute(
        service,
        [ToolCall("one", tool.name, '{"command":"safe"}' if effect is ToolEffect.SHELL else "{}")],
        PLAN_MODE.tool_policy,
        PLAN_MODE,
    )

    assert isinstance(plan, ToolExecutionBlocked) is blocked
    assert tool.executed is (not blocked)
    if effect is ToolEffect.EXTERNAL:
        assert approver.requests[0][1] is True
        assert results[0].ok


@pytest.mark.parametrize("failure_index", [0, 1, 2], ids=("first-fails", "middle-fails", "last-fails"))
async def test_concurrent_batch_retains_successes_around_failure(tmp_path, failure_index) -> None:
    tools = [IntegrationTool(f"tool_{index}", ToolEffect.READ, fail=index == failure_index) for index in range(3)]
    registry = ToolRegistry()
    registry.register_many(tools)
    service = ToolExecutionService(registry, execution_context(tmp_path))

    plan, results = await execute(
        service,
        [ToolCall(str(index), tool.name, "{}") for index, tool in enumerate(tools)],
    )

    assert plan.batches[0].safety is ToolSafety.READ_ONLY
    assert [result.tool_name for result in results] == [tool.name for tool in tools]
    assert [result.ok for result in results] == [index != failure_index for index in range(3)]


@pytest.mark.parametrize(
    ("layer", "action", "expected_ok", "approval_count"),
    [
        ("user", PermissionAction.ALLOW, True, 0),
        ("project", PermissionAction.DENY, False, 0),
        ("local", PermissionAction.ASK, True, 1),
    ],
    ids=("user-allow", "project-deny", "local-ask"),
)
async def test_rule_layer_decision_flows_into_real_write(tmp_path, layer, action, expected_ok, approval_count) -> None:
    permission_engine, loader = engine(tmp_path)
    selected_path = getattr(loader.paths, layer)
    target = tmp_path / "note.txt"
    selected_path.write_text(
        yaml.safe_dump({"rules": [{"match": f"write_file({target})", "action": action.value}]}),
        encoding="utf-8",
    )
    approver = ChoiceApprover(ApprovalChoice.ALLOW_ONCE)
    permission = PermissionService(PermissionState(), engine=permission_engine, approver=approver)
    service = ToolExecutionService(create_default_tool_registry(), execution_context(tmp_path), permission)

    _plan, results = await execute(
        service,
        [ToolCall("one", "write_file", '{"path":"note.txt","content":"value"}')],
    )

    assert results[0].ok is expected_ok
    assert len(approver.requests) == approval_count
    assert (tmp_path / "note.txt").exists() is expected_ok


@pytest.mark.parametrize(
    ("effect", "origin", "safety", "approval_count"),
    [
        (ToolEffect.READ, ToolOrigin.BUILTIN, ToolSafety.READ_ONLY, 0),
        (ToolEffect.WRITE, ToolOrigin.BUILTIN, ToolSafety.SIDE_EFFECT, 1),
        (ToolEffect.SHELL, ToolOrigin.BUILTIN, ToolSafety.SIDE_EFFECT, 0),
        (ToolEffect.EXTERNAL, ToolOrigin.MCP, ToolSafety.MCP_EXTERNAL, 1),
    ],
    ids=("custom-read", "custom-write", "custom-shell", "custom-external"),
)
async def test_custom_descriptor_drives_plan_permission_and_execution(
    tmp_path,
    effect,
    origin,
    safety,
    approval_count,
) -> None:
    tool = IntegrationTool("custom", effect, origin=origin)
    registry = ToolRegistry()
    registry.register(tool)
    approver = ChoiceApprover(ApprovalChoice.ALLOW_ONCE, mcp=True)
    permission_engine, _loader = engine(tmp_path, allowed_names={"custom"})
    permission = PermissionService(
        PermissionState(),
        engine=permission_engine,
        approver=approver,
    )
    service = ToolExecutionService(registry, execution_context(tmp_path), permission)
    arguments = '{"command":"printf safe"}' if effect is ToolEffect.SHELL else "{}"

    plan, results = await execute(service, [ToolCall("one", tool.name, arguments)])

    assert plan.batches[0].safety is safety
    assert results[0].ok
    assert tool.executed
    assert len(approver.requests) == approval_count
