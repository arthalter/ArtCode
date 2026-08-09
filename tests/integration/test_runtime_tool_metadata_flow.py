from __future__ import annotations

import pytest

from artcode.agent import PLAN_MODE, ToolAccessPolicy
from artcode.permissions.service import PermissionService
from artcode.tools.execution import ToolExecutionService, ToolSafety
from artcode.permissions import (
    PermissionAction,
    PermissionEngine,
    PermissionRequest,
    PermissionState,
    RuleLoader,
    RulePaths,
)
from artcode.providers.tool_calls import ToolCall
from artcode.security import DangerousCommandValidator
from artcode.tools import (
    DescriptorBackedTool,
    ToolDescriptor,
    ToolEffect,
    ToolEnvironment,
    ToolOrigin,
    ToolRegistry,
)

pytestmark = pytest.mark.ch10_5


class DescriptorOnlyTool(DescriptorBackedTool):
    def __init__(self, descriptor: ToolDescriptor) -> None:
        self.descriptor = descriptor


def metadata(effect: ToolEffect) -> ToolDescriptor:
    is_external = effect is ToolEffect.EXTERNAL
    return ToolDescriptor(
        f"custom_{effect.value}",
        "custom test tool",
        {"type": "object", "properties": {}},
        effect,
        ToolOrigin.MCP if is_external else ToolOrigin.BUILTIN,
        not is_external,
    )


def registry_for(effect: ToolEffect) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(DescriptorOnlyTool(metadata(effect)))
    return registry


@pytest.mark.parametrize(
    ("effect", "visible"),
    [
        (ToolEffect.READ, True),
        (ToolEffect.WRITE, False),
        (ToolEffect.EXTERNAL, True),
    ],
    ids=("read", "write", "external"),
)
def test_one_descriptor_declaration_drives_plan_visibility(effect: ToolEffect, visible: bool) -> None:
    exported = registry_for(effect).openai_tools(include_internal_metadata=True)
    selected = PLAN_MODE.tool_policy.filter_openai_tools(exported)
    assert bool(selected) is visible


@pytest.mark.parametrize(
    ("effect", "safety"),
    [
        (ToolEffect.READ, ToolSafety.READ_ONLY),
        (ToolEffect.WRITE, ToolSafety.SIDE_EFFECT),
        (ToolEffect.SHELL, ToolSafety.SIDE_EFFECT),
        (ToolEffect.EXTERNAL, ToolSafety.MCP_EXTERNAL),
    ],
    ids=("read", "write", "shell", "external"),
)
def test_same_descriptor_declaration_drives_batch_planning(tmp_path, effect: ToolEffect, safety: ToolSafety) -> None:
    descriptor = metadata(effect)
    registry = registry_for(effect)
    executor = ToolExecutionService(
        registry,
        ToolEnvironment.from_workspace(tmp_path),
        PermissionService(PermissionState()),
    )
    plan = executor.build_plan(
        [ToolCall("call", descriptor.name, "{}")],
        ToolAccessPolicy(),
    )
    assert plan.batches[0].safety is safety


@pytest.mark.parametrize(
    ("effect", "expected"),
    [
        (ToolEffect.READ, PermissionAction.ALLOW),
        (ToolEffect.WRITE, PermissionAction.ASK),
        (ToolEffect.SHELL, PermissionAction.ALLOW),
    ],
    ids=("read", "write", "shell"),
)
def test_same_descriptor_declaration_drives_permission_defaults(
    tmp_path,
    effect: ToolEffect,
    expected: PermissionAction,
) -> None:
    descriptor = metadata(effect)
    loader = RuleLoader(RulePaths(tmp_path / "user.yml", tmp_path / "project.yml", tmp_path / "local.yml"))
    engine = PermissionEngine(loader, DangerousCommandValidator.load())
    decision = engine.decide(
        PermissionRequest(
            descriptor.name,
            "git status" if effect is ToolEffect.SHELL else "target",
            tmp_path,
            effect=descriptor.effect.value,
            rule_configurable=descriptor.rule_configurable,
        ),
        PermissionState(),
    )
    assert decision.action is expected
