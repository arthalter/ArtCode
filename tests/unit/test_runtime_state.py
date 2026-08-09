from __future__ import annotations

import pytest

from artcode.agent import NORMAL_AGENT_MODE, PLAN_MODE, TokenUsage
from artcode.commands import DisplayMode
from artcode.permissions import PermissionMode, PermissionSnapshot, PermissionState, ShellPolicy
from artcode.runtime.state import RuntimeState
from artcode.tools import (
    DescriptorBackedTool,
    ToolDescriptor,
    ToolEffect,
    ToolEnvironment,
    ToolOrigin,
    ToolRegistry,
    ToolRunContext,
)

pytestmark = pytest.mark.ch10_5


def snapshot(state: RuntimeState):
    return state.status_snapshot(
        model="model",
        workspace="/workspace",
        seatbelt_status="ready",
        session_id="session",
        session_state="restored",
        estimated_context_tokens=123,
        context_window_tokens=1_000_000,
    )


@pytest.mark.parametrize("mode", list(PermissionMode), ids=lambda value: value.value)
def test_runtime_state_permission_mode_has_one_snapshot_source(mode: PermissionMode) -> None:
    state = RuntimeState(PermissionState())
    state.set_permission_mode(mode)
    assert state.permission.mode is mode
    assert state.permission_snapshot.mode is mode
    assert snapshot(state).permission_mode == mode.value


@pytest.mark.parametrize("policy", list(ShellPolicy), ids=lambda value: value.value)
def test_runtime_state_shell_policy_has_one_snapshot_source(policy: ShellPolicy) -> None:
    state = RuntimeState(PermissionState())
    state.set_shell_policy(policy)
    assert state.permission.shell_policy is policy
    assert state.permission_snapshot.shell_policy is policy
    assert snapshot(state).shell_policy == policy.value


@pytest.mark.parametrize("mode", list(DisplayMode), ids=lambda value: value.value.lower())
def test_runtime_state_display_mode_has_one_snapshot_source(mode: DisplayMode) -> None:
    state = RuntimeState(PermissionState())
    state.set_display_mode(mode)
    assert state.display_mode is mode
    assert snapshot(state).display_mode is mode


@pytest.mark.parametrize(
    "usage",
    [TokenUsage(prompt_tokens=1), TokenUsage(total_tokens=9), TokenUsage(cached_tokens=7)],
    ids=("prompt", "total", "cache"),
)
def test_runtime_state_usage_has_one_snapshot_source(usage: TokenUsage) -> None:
    state = RuntimeState(PermissionState())
    state.record_usage(usage)
    assert state.last_token_usage is usage
    assert snapshot(state).last_token_usage is usage


def test_permission_snapshot_is_detached_from_later_runtime_mutation() -> None:
    state = RuntimeState(PermissionState())
    before = state.permission_snapshot
    state.set_permission_mode(PermissionMode.FULL)
    state.set_shell_policy(ShellPolicy.UNSANDBOXED_ASK)
    assert before == PermissionSnapshot(PermissionMode.DEFAULT, ShellPolicy.SANDBOX_AUTO)
    assert state.permission_snapshot != before


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        ("model", "model"),
        ("workspace", "/workspace"),
        ("seatbelt_status", "ready"),
        ("session_id", "session"),
        ("session_state", "restored"),
        ("estimated_context_tokens", 123),
        ("context_window_tokens", 1_000_000),
        ("last_token_usage", None),
    ],
    ids=("model", "workspace", "seatbelt", "session-id", "session-state", "estimate", "window", "usage"),
)
def test_runtime_status_snapshot_is_an_immutable_explicit_projection(field: str, expected) -> None:
    status = snapshot(RuntimeState(PermissionState()))
    assert getattr(status, field) == expected
    with pytest.raises((AttributeError, TypeError)):
        setattr(status, field, expected)


@pytest.mark.parametrize(
    ("name", "effect", "origin", "rule_configurable"),
    [
        ("reader", ToolEffect.READ, ToolOrigin.BUILTIN, True),
        ("writer", ToolEffect.WRITE, ToolOrigin.BUILTIN, True),
        ("shell", ToolEffect.SHELL, ToolOrigin.BUILTIN, True),
        ("external", ToolEffect.EXTERNAL, ToolOrigin.MCP, False),
        ("fixed_reader", ToolEffect.READ, ToolOrigin.BUILTIN, False),
        ("读取器", ToolEffect.READ, ToolOrigin.BUILTIN, True),
    ],
    ids=("read", "write", "shell", "mcp", "fixed", "unicode"),
)
def test_tool_descriptor_accepts_complete_single_source_metadata(
    name: str,
    effect: ToolEffect,
    origin: ToolOrigin,
    rule_configurable: bool,
) -> None:
    descriptor = ToolDescriptor(name, "description", {"type": "object"}, effect, origin, rule_configurable)
    assert descriptor.name == name
    assert descriptor.effect is effect
    assert descriptor.origin is origin
    assert descriptor.rule_configurable is rule_configurable


@pytest.mark.parametrize(
    "kwargs",
    [
        {"name": ""},
        {"name": "   "},
        {"description": ""},
        {"description": "   "},
        {"parameters_schema": []},
        {"effect": "read"},
        {"origin": "builtin"},
        {"effect": ToolEffect.EXTERNAL, "origin": ToolOrigin.MCP, "rule_configurable": True},
    ],
    ids=("empty-name", "blank-name", "empty-description", "blank-description", "schema", "effect", "origin", "mcp-rule"),
)
def test_tool_descriptor_rejects_incomplete_or_conflicting_metadata(kwargs: dict) -> None:
    values = {
        "name": "tool",
        "description": "description",
        "parameters_schema": {"type": "object"},
        "effect": ToolEffect.READ,
        "origin": ToolOrigin.BUILTIN,
        "rule_configurable": True,
    }
    values.update(kwargs)
    with pytest.raises((TypeError, ValueError)):
        ToolDescriptor(**values)


class MetadataOnlyTool(DescriptorBackedTool):
    def __init__(self, descriptor: ToolDescriptor) -> None:
        self.descriptor = descriptor


@pytest.mark.parametrize(
    ("effect", "origin", "rule_configurable"),
    [
        (ToolEffect.READ, ToolOrigin.BUILTIN, True),
        (ToolEffect.WRITE, ToolOrigin.BUILTIN, True),
        (ToolEffect.SHELL, ToolOrigin.BUILTIN, True),
        (ToolEffect.EXTERNAL, ToolOrigin.MCP, False),
    ],
    ids=("read", "write", "shell", "external"),
)
def test_registry_exports_internal_policy_metadata_from_descriptor_only(
    effect: ToolEffect,
    origin: ToolOrigin,
    rule_configurable: bool,
) -> None:
    descriptor = ToolDescriptor("tool", "description", {"type": "object"}, effect, origin, rule_configurable)
    registry = ToolRegistry()
    registry.register(MetadataOnlyTool(descriptor))
    exported = registry.openai_tools(include_internal_metadata=True)[0]
    assert registry.descriptor("tool") is descriptor
    assert exported["x-artcode-effect"] == effect.value
    assert exported["x-artcode-origin"] == origin.value
    assert exported["x-artcode-rule-configurable"] is rule_configurable


@pytest.mark.parametrize("mode", [NORMAL_AGENT_MODE, PLAN_MODE], ids=("normal", "plan"))
def test_tool_run_context_combines_stable_environment_with_permission_snapshot(tmp_path, mode) -> None:
    environment = ToolEnvironment(
        ToolEnvironment.from_workspace(tmp_path).path_policy,
        default_cwd=tmp_path,
        artifact_store=object(),
    )
    permission = PermissionSnapshot(PermissionMode.EDIT, ShellPolicy.SANDBOX_ASK)
    context = ToolRunContext(environment, mode, permission)
    assert context.environment is environment
    assert context.path_policy is environment.path_policy
    assert context.default_cwd == tmp_path
    assert context.artifact_store is environment.artifact_store
    assert context.shell_policy is ShellPolicy.SANDBOX_ASK
