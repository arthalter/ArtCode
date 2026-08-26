from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from artcode.agent import ToolAccessPolicy
from artcode.tools import ToolDescriptor, ToolEffect, ToolOrigin

from .models import RoleDefinition


_FORBIDDEN_NAMES = frozenset({"agent", "task_list", "task_get", "task_cancel", "ask_user"})


@dataclass(frozen=True)
class SubagentCapabilities:
    policy: ToolAccessPolicy
    tool_names: frozenset[str]
    requires_worktree: bool


def compute_capabilities(
    parent_policy: ToolAccessPolicy,
    descriptors: Iterable[ToolDescriptor],
    role: RoleDefinition | None,
    background_tools: frozenset[str],
    parent_tool_names: frozenset[str] | None = None,
) -> SubagentCapabilities:
    allowed: set[str] = set()
    writing = False
    for descriptor in descriptors:
        if descriptor.name in _FORBIDDEN_NAMES:
            continue
        if descriptor.name not in background_tools:
            continue
        if not descriptor.subagent_allowed or descriptor.origin is not ToolOrigin.BUILTIN:
            # MCP calls need an interactive confirmation and system tools can
            # control parent state, so neither is delegable.
            continue
        if not parent_policy.allows(descriptor):
            continue
        if parent_tool_names is not None and descriptor.name not in parent_tool_names:
            continue
        if role is not None:
            if descriptor.name not in role.tool_allow:
                continue
            if descriptor.name in role.tool_deny:
                continue
        allowed.add(descriptor.name)
        writing = writing or descriptor.effect in {ToolEffect.WRITE, ToolEffect.SHELL}
    return SubagentCapabilities(
        ToolAccessPolicy(allowed_names=frozenset(allowed), allow_system=False),
        frozenset(allowed),
        writing or bool(role and role.worktree),
    )
