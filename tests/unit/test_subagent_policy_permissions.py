from __future__ import annotations

from pathlib import Path

import pytest

from artcode.agent import NORMAL_AGENT_MODE, PLAN_MODE
from artcode.permissions import (
    PermissionAction,
    PermissionDecision,
    PermissionMode,
    PermissionSnapshot,
    PermissionState,
    RuleSource,
    ShellPolicy,
)
from artcode.subagents.models import IsolationMode, RoleDefinition, RoleSource
from artcode.subagents.permissions import SubagentPermissionService, restrict_permission
from artcode.subagents.policy import compute_capabilities
from artcode.tools import (
    PreparedToolCall,
    ToolDescriptor,
    ToolEffect,
    ToolEnvironment,
    ToolOrigin,
    ToolPreview,
    ToolRunContext,
    create_default_tool_registry,
)


SAFE = frozenset(
    {"read_file", "write_file", "edit_file", "run_command", "find_files", "search_text"}
)


def _role(
    allow: frozenset[str],
    *,
    mode: PermissionMode = PermissionMode.DEFAULT,
    isolation: IsolationMode = IsolationMode.NONE,
) -> RoleDefinition:
    return RoleDefinition(
        "role",
        "role",
        "system\n",
        RoleSource.PROJECT,
        Path("role.md"),
        allow,
        frozenset(),
        "inherit",
        10,
        mode,
        isolation,
    )


def test_exact_six_builtin_tools_are_explicitly_delegable() -> None:
    descriptors = create_default_tool_registry().descriptors()

    assert {item.name for item in descriptors if item.subagent_allowed} == SAFE
    assert all(item.origin is ToolOrigin.BUILTIN for item in descriptors)


def test_capabilities_are_intersection_of_parent_background_snapshot_and_role() -> None:
    descriptors = create_default_tool_registry().descriptors()
    capabilities = compute_capabilities(
        NORMAL_AGENT_MODE.tool_policy,
        descriptors,
        _role(frozenset({"read_file", "write_file", "run_command"}), isolation=IsolationMode.WORKTREE),
        frozenset({"read_file", "write_file"}),
        frozenset({"read_file", "run_command"}),
    )

    assert capabilities.tool_names == frozenset({"read_file"})
    assert capabilities.requires_worktree is True  # explicit role isolation survives narrowing


def test_plan_parent_removes_write_and_shell_from_child_capabilities() -> None:
    capabilities = compute_capabilities(
        PLAN_MODE.tool_policy,
        create_default_tool_registry().descriptors(),
        _role(SAFE, isolation=IsolationMode.WORKTREE),
        SAFE,
    )

    assert capabilities.tool_names == frozenset(
        {"read_file", "find_files", "search_text"}
    )


def test_role_permission_can_only_reduce_parent_and_never_keeps_unsandboxed_shell() -> None:
    parent_default = PermissionSnapshot(
        PermissionMode.DEFAULT, ShellPolicy.UNSANDBOXED_ASK
    )
    parent_full = PermissionSnapshot(
        PermissionMode.FULL, ShellPolicy.UNSANDBOXED_ASK
    )

    child_from_default = restrict_permission(
        parent_default, _role(SAFE, mode=PermissionMode.FULL)
    )
    child_from_full = restrict_permission(
        parent_full, _role(SAFE, mode=PermissionMode.EDIT)
    )

    assert child_from_default.snapshot() == PermissionSnapshot(
        PermissionMode.DEFAULT, ShellPolicy.SANDBOX_AUTO
    )
    assert child_from_full.snapshot() == PermissionSnapshot(
        PermissionMode.EDIT, ShellPolicy.SANDBOX_AUTO
    )


class _DecisionEngine:
    def __init__(self, action: PermissionAction) -> None:
        self.action = action

    def decide(self, _request, _permission) -> PermissionDecision:
        return PermissionDecision(self.action, RuleSource.PROJECT, "fixture")


class _NeverApprove:
    def __init__(self) -> None:
        self.calls = 0

    async def request_approval(self, _request):
        self.calls += 1
        raise AssertionError("subagent approval port must not be called")


@pytest.mark.parametrize(
    ("action", "expected_decision", "error_code"),
    (
        (PermissionAction.ALLOW, "allowed", None),
        (PermissionAction.DENY, "denied", "permission_denied"),
        (PermissionAction.ASK, "auto_denied", "approval_required_in_subagent"),
    ),
)
async def test_noninteractive_permission_decisions_are_audited_without_raw_secret(
    tmp_path: Path,
    action: PermissionAction,
    expected_decision: str,
    error_code: str | None,
) -> None:
    state = PermissionState(mode=PermissionMode.EDIT)
    approver = _NeverApprove()
    service = SubagentPermissionService(
        "task-deadbeef",
        state,
        engine=_DecisionEngine(action),
        approver=approver,
    )
    descriptor = ToolDescriptor(
        "write_file",
        "write",
        {"type": "object"},
        ToolEffect.WRITE,
        subagent_allowed=True,
    )
    secret = "SECRET-RAW-TARGET"
    prepared = PreparedToolCall(
        object(),
        {"path": secret},
        ToolPreview("write_file", "write", secret),
    )
    environment = ToolEnvironment.from_workspace(tmp_path)
    context = ToolRunContext(environment, NORMAL_AGENT_MODE, state.snapshot())

    result = await service.authorize(descriptor, prepared, context)

    assert (None if result is None else result.error_code) == error_code
    assert approver.calls == 0
    assert service.events[-1].decision == expected_decision
    assert service.events[-1].task_id == "task-deadbeef"
    assert secret not in service.events[-1].target_summary
    assert service.events[-1].target_summary.startswith("sha256:")
