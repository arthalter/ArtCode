"""Public Tool Interface for catalog, policy, approval, and batch execution."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping, Protocol, runtime_checkable

from .workspace import Workspace


class ToolEffect(StrEnum):
    OBSERVE = "observe"
    CHANGE = "change"
    EXTERNAL = "external"
    CONTROL = "control"


class ToolOrigin(StrEnum):
    BUILTIN = "builtin"
    MCP = "mcp"
    SYSTEM = "system"


class RunMode(StrEnum):
    CHAT = "chat"
    PLAN = "plan"
    ACT = "act"


class ToolSource(StrEnum):
    MAIN = "main"
    SUBAGENT = "subagent"
    ISOLATED_SKILL = "isolated_skill"


class PermissionMode(StrEnum):
    DEFAULT = "default"
    EDIT = "edit"
    FULL = "full"


class ShellPolicy(StrEnum):
    SANDBOX_AUTO = "sandbox_auto"
    SANDBOX_ASK = "sandbox_ask"
    EXPLICIT_UNSAFE = "explicit_unsafe"


class ApprovalChoice(StrEnum):
    ALLOW_ONCE = "allow_once"
    DENY_ONCE = "deny_once"
    ALLOW_ALWAYS = "allow_always"
    DENY_ALWAYS = "deny_always"


class McpLoading(StrEnum):
    EAGER = "eager"
    LAZY = "lazy"


class McpServerSource(StrEnum):
    USER = "user"
    PROJECT = "project"


class McpServerState(StrEnum):
    DISABLED = "disabled"
    REJECTED = "rejected"
    INVALID = "invalid"
    READY = "ready"
    UNAVAILABLE = "unavailable"
    CLOSED = "closed"


@dataclass(frozen=True, slots=True)
class McpServerReport:
    name: str
    source: McpServerSource
    state: McpServerState
    tool_count: int = 0
    detail: str = ""
    truncated: bool = False


@dataclass(frozen=True, slots=True)
class McpReport:
    configured_count: int
    servers: tuple[McpServerReport, ...]
    discovered_tool_count: int
    active_tool_count: int
    loading: McpLoading

    @property
    def connected_count(self) -> int:
        return sum(item.state is McpServerState.READY for item in self.servers)


@dataclass(frozen=True, slots=True)
class McpToolHit:
    name: str
    description: str
    server: str
    active: bool


class McpServerApprover(Protocol):
    async def approve_mcp_server(self, name: str, summary: str) -> bool: ...


@dataclass(frozen=True, slots=True)
class ToolDescriptor:
    name: str
    description: str
    parameters_json: str
    effect: ToolEffect
    origin: ToolOrigin = ToolOrigin.BUILTIN
    subagent_allowed: bool = True
    rule_configurable: bool = True


@dataclass(frozen=True, slots=True)
class ToolCall:
    id: str
    name: str
    arguments_json: str

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id:
            raise ValueError("Tool call id must be non-empty")
        if not isinstance(self.name, str):
            raise TypeError("Tool call name must be text")
        if not isinstance(self.arguments_json, str):
            raise TypeError("Tool call arguments_json must be text")


@dataclass(frozen=True, slots=True)
class ToolResult:
    call_id: str
    tool_name: str
    ok: bool
    content: str
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class PermissionRule:
    tool_name: str
    target: str
    allow: bool


@dataclass(frozen=True, slots=True)
class PermissionSnapshot:
    mode: PermissionMode
    shell_policy: ShellPolicy
    rules: tuple[PermissionRule, ...]


@dataclass(frozen=True, slots=True)
class ToolRun:
    descriptors: tuple[ToolDescriptor, ...]
    mode: RunMode
    source: ToolSource
    permission: PermissionSnapshot
    workspace: Workspace
    catalog_id: str
    allowed_tools: frozenset[str] | None
    execution_data: object | None = None


@dataclass(frozen=True, slots=True)
class ApprovalRequest:
    tool_name: str
    target: str
    effect: ToolEffect
    workspace: Path
    permission_mode: PermissionMode
    shell_policy: ShellPolicy
    source: ToolSource


class Approver(Protocol):
    async def approve(self, request: ApprovalRequest) -> ApprovalChoice: ...


@runtime_checkable
class Tool(Protocol):
    async def start_mcp(
        self,
        workspace: Workspace,
        user_config: Mapping[str, Any],
        project_config: Mapping[str, Any],
        *,
        loading: McpLoading = McpLoading.EAGER,
        approver: McpServerApprover | None = None,
    ) -> McpReport: ...

    def search_mcp(self, query: str, *, limit: int = 5) -> tuple[McpToolHit, ...]: ...

    def activate_mcp(self, name: str) -> bool: ...

    def open_run(
        self,
        workspace: Workspace,
        mode: RunMode,
        *,
        source: ToolSource = ToolSource.MAIN,
        allowed_tools: frozenset[str] | None = None,
    ) -> ToolRun: ...

    async def execute_batch(
        self,
        run: ToolRun,
        calls: tuple[ToolCall, ...],
        *,
        approver: Approver | None = None,
    ) -> tuple[ToolResult, ...]: ...

    def set_permission_mode(self, mode: PermissionMode) -> PermissionSnapshot: ...

    def set_shell_policy(self, policy: ShellPolicy) -> PermissionSnapshot: ...

    def state(self) -> PermissionSnapshot: ...

    async def close(self) -> None: ...


__all__ = [
    "ApprovalChoice",
    "ApprovalRequest",
    "Approver",
    "McpLoading",
    "McpReport",
    "McpServerApprover",
    "McpServerReport",
    "McpServerSource",
    "McpServerState",
    "McpToolHit",
    "PermissionMode",
    "PermissionRule",
    "PermissionSnapshot",
    "RunMode",
    "ShellPolicy",
    "Tool",
    "ToolCall",
    "ToolDescriptor",
    "ToolEffect",
    "ToolOrigin",
    "ToolResult",
    "ToolRun",
    "ToolSource",
]
