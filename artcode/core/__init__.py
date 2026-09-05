"""Public architecture manifest for the ch14 core.

The concrete module Interfaces are introduced by T2--T12.  This manifest is
deliberately limited to ownership and dependency rules so T1 does not freeze
placeholder Interfaces before their contract tests exist.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Mapping


@dataclass(frozen=True, slots=True)
class CoreModuleRule:
    """Architecture facts shared by dependency checks and design reviews."""

    owns: tuple[str, ...]
    may_depend_on: frozenset[str]


_RULES = {
    "application": CoreModuleRule(
        owns=("application_lifecycle", "composed_configuration", "foreground_operation"),
        may_depend_on=frozenset(
            {"session", "agent", "model", "tool", "workspace", "skill", "subagent"}
        ),
    ),
    "session": CoreModuleRule(
        owns=(
            "transcript",
            "session_lock",
            "recovery_state",
            "latest_plan",
            "notices",
            "summaries",
            "long_term_memory",
            "committed_usage",
            "protocol_metadata_values",
        ),
        may_depend_on=frozenset({"model", "tool"}),
    ),
    "agent": CoreModuleRule(
        owns=("run_round", "temporary_text", "tool_protocol", "run_usage"),
        may_depend_on=frozenset({"session", "model", "tool"}),
    ),
    "model": CoreModuleRule(
        owns=("provider_connections", "provider_protocol_interpretation"),
        may_depend_on=frozenset(),
    ),
    "tool": CoreModuleRule(
        owns=(
            "tool_catalog",
            "tool_effects",
            "permission_policy",
            "shell_policy",
            "permission_rules",
            "mcp_sessions",
            "mcp_activation",
        ),
        may_depend_on=frozenset({"workspace"}),
    ),
    "workspace": CoreModuleRule(
        owns=(
            "workspace_root",
            "path_policy",
            "processes",
            "seatbelt",
            "result_files",
            "worktrees",
        ),
        may_depend_on=frozenset(),
    ),
    "skill": CoreModuleRule(
        owns=("skill_catalog", "skill_activation", "last_valid_skill_versions"),
        may_depend_on=frozenset({"session", "agent", "model", "tool"}),
    ),
    "subagent": CoreModuleRule(
        owns=("role_catalog", "task_queue", "child_runs", "task_notifications"),
        may_depend_on=frozenset({"session", "agent", "model", "tool", "workspace"}),
    ),
}

CORE_ARCHITECTURE: Final[Mapping[str, CoreModuleRule]] = MappingProxyType(_RULES)
CORE_MODULES: Final[tuple[str, ...]] = tuple(_RULES)

__all__ = ["CORE_ARCHITECTURE", "CORE_MODULES", "CoreModuleRule"]
