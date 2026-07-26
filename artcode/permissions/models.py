from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class PermissionAction(StrEnum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"
    NO_MATCH = "no_match"


class PermissionMode(StrEnum):
    DEFAULT = "default"
    EDIT = "edit"
    FULL = "full"

    def default_for(self, tool_name: str) -> PermissionAction:
        if tool_name in {"read_file", "find_files", "search_text"}:
            return PermissionAction.ALLOW
        if tool_name in {"write_file", "edit_file"}:
            return PermissionAction.ASK if self is PermissionMode.DEFAULT else PermissionAction.ALLOW
        raise ValueError(f"权限模式不负责工具：{tool_name}")


class ShellPolicy(StrEnum):
    SANDBOX_AUTO = "auto"
    SANDBOX_ASK = "ask"
    UNSANDBOXED_ASK = "off"

    @property
    def default_action(self) -> PermissionAction:
        if self is ShellPolicy.SANDBOX_AUTO:
            return PermissionAction.ALLOW
        return PermissionAction.ASK

    @property
    def uses_sandbox(self) -> bool:
        return self is not ShellPolicy.UNSANDBOXED_ASK


@dataclass
class PermissionState:
    mode: PermissionMode = PermissionMode.DEFAULT
    shell_policy: ShellPolicy = ShellPolicy.SANDBOX_AUTO


class RuleSource(StrEnum):
    USER = "user"
    PROJECT = "project"
    LOCAL = "local"
    MODE = "mode"
    SHELL_POLICY = "shell_policy"
    PLAN = "plan"
    PATH = "path"
    SENSITIVE = "sensitive"
    DANGEROUS_COMMAND = "dangerous_command"


@dataclass(frozen=True)
class PermissionRequest:
    tool_name: str
    target: str
    workspace: Path
    plan_mode: bool = False


@dataclass(frozen=True)
class PermissionDecision:
    action: PermissionAction
    source: RuleSource
    reason: str
    rule_index: int | None = None
    rule_file: Path | None = None

    def __post_init__(self) -> None:
        if self.action is PermissionAction.NO_MATCH:
            raise ValueError("最终权限决定不能是 NO_MATCH")


class ApprovalChoice(StrEnum):
    ALLOW_ONCE = "allow_once"
    DENY_ONCE = "deny_once"
    ALLOW_ALWAYS = "allow_always"
    DENY_ALWAYS = "deny_always"


@dataclass(frozen=True)
class ApprovalRequest:
    tool_name: str
    target: str
    workspace: Path
    permission_mode: PermissionMode
    shell_policy: ShellPolicy
    source: str
