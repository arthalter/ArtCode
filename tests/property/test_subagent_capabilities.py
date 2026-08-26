from __future__ import annotations

import string

from hypothesis import given, settings, strategies as st

from artcode.agent.modes import NORMAL_AGENT_MODE, PLAN_MODE
from artcode.subagents.models import RoleDefinition, RoleSource, IsolationMode
from artcode.subagents.policy import compute_capabilities
from artcode.tools import ToolDescriptor, ToolEffect, ToolOrigin
from artcode.permissions import PermissionMode
from pathlib import Path


def _descriptor(name: str, effect: ToolEffect) -> ToolDescriptor:
    return ToolDescriptor(
        name=name,
        description="property test tool",
        parameters_schema={"type": "object", "properties": {}, "additionalProperties": False},
        effect=effect,
        origin=ToolOrigin.BUILTIN,
        rule_configurable=True,
        subagent_allowed=True,
    )


_NAMES = ["read_file", "write_file", "edit_file", "run_command", "find_files", "search_text", "mcp_city"]
_EFFECTS = [ToolEffect.READ, ToolEffect.WRITE, ToolEffect.SHELL, ToolEffect.READ, ToolEffect.READ, ToolEffect.READ, ToolEffect.EXTERNAL]
_DESCRIPTORS = tuple(_descriptor(name, effect) for name, effect in zip(_NAMES, _EFFECTS))

_ALLOWED_SET = st.frozensets(st.sampled_from(_NAMES[:6]))
_NAME_SET = st.frozensets(st.sampled_from(_NAMES))
_MODE = st.sampled_from([NORMAL_AGENT_MODE, PLAN_MODE])


def _role(allow: frozenset[str], deny: frozenset[str], tier: str = "inherit") -> RoleDefinition:
    return RoleDefinition(
        name="prop-role",
        description="property test role",
        system_prompt="完成子任务。",
        source=RoleSource.PROJECT,
        path=Path("/tmp/prop-role.md"),
        tool_allow=frozenset(allow) - frozenset(deny),
        tool_deny=frozenset(deny),
        model_tier=tier,
        max_rounds=10,
        permission_mode=PermissionMode.DEFAULT,
        isolation=IsolationMode.NONE,
    )


@settings(max_examples=200, deadline=None)
@given(
    parent=_MODE,
    background=_ALLOWED_SET,
    role_allow=_NAME_SET,
    role_deny=_NAME_SET,
    parent_snapshot=_NAME_SET,
)
def test_capabilities_never_exceed_any_single_bound(
    parent,
    background: frozenset[str],
    role_allow: frozenset[str],
    role_deny: frozenset[str],
    parent_snapshot: frozenset[str],
) -> None:
    role = _role(role_allow, role_deny)
    caps = compute_capabilities(
        parent.tool_policy,
        _DESCRIPTORS,
        role,
        background,
        parent_tool_names=parent_snapshot,
    )
    for name in caps.tool_names:
        descriptor = next(item for item in _DESCRIPTORS if item.name == name)
        # inside every independent bound
        assert name in background
        assert descriptor.subagent_allowed
        assert descriptor.origin is ToolOrigin.BUILTIN
        assert parent.tool_policy.allows(descriptor)
        assert name in parent_snapshot
        assert name in role_allow
        assert name not in role_deny
        # never forbidden system names
        assert name not in {"agent", "task_list", "task_get", "task_cancel", "ask_user"}
    # Plan mode: writes and shell can never appear
    if parent is PLAN_MODE:
        for name in caps.tool_names:
            descriptor = next(item for item in _DESCRIPTORS if item.name == name)
            assert descriptor.effect not in {ToolEffect.WRITE, ToolEffect.SHELL}


@settings(max_examples=150, deadline=None)
@given(
    background=_ALLOWED_SET,
    role_allow=_NAME_SET,
    role_deny=_NAME_SET,
)
def test_capabilities_require_worktree_when_writing_or_shell(
    background: frozenset[str],
    role_allow: frozenset[str],
    role_deny: frozenset[str],
) -> None:
    role = _role(role_allow, role_deny)
    caps = compute_capabilities(NORMAL_AGENT_MODE.tool_policy, _DESCRIPTORS, role, background)
    writing = any(
        descriptor.effect in {ToolEffect.WRITE, ToolEffect.SHELL}
        for descriptor in _DESCRIPTORS
        if descriptor.name in caps.tool_names
    )
    assert caps.requires_worktree == writing


@settings(max_examples=100, deadline=None)
@given(
    background=_ALLOWED_SET,
    allow_deny=st.frozensets(st.sampled_from(_NAMES[:6])),
)
def test_role_cannot_restore_globally_blocked_tools(
    background: frozenset[str],
    allow_deny: frozenset[str],
) -> None:
    """A role whitelist can never bring back tools outside the background set."""
    role = _role(allow_deny, frozenset())
    caps = compute_capabilities(NORMAL_AGENT_MODE.tool_policy, _DESCRIPTORS, role, background)
    assert caps.tool_names <= background
    assert caps.tool_names <= allow_deny
