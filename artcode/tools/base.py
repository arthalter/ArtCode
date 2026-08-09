from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping, Protocol

from artcode.permissions import PermissionSnapshot, PermissionState, ShellPolicy
from artcode.sandbox import SeatbeltSession

from .policy import AllowedPathPolicy
from .results import ToolResult

if TYPE_CHECKING:
    from artcode.agent.modes import AgentMode


class ToolOrigin(StrEnum):
    BUILTIN = "builtin"
    MCP = "mcp"


class ToolEffect(StrEnum):
    READ = "read"
    WRITE = "write"
    SHELL = "shell"
    EXTERNAL = "external"


@dataclass(frozen=True)
class ToolDescriptor:
    name: str
    description: str
    parameters_schema: Mapping[str, Any]
    effect: ToolEffect
    origin: ToolOrigin = ToolOrigin.BUILTIN
    rule_configurable: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("tool descriptor name must be a non-empty string")
        if not isinstance(self.description, str) or not self.description.strip():
            raise ValueError("tool descriptor description must be a non-empty string")
        if not isinstance(self.parameters_schema, Mapping):
            raise TypeError("tool descriptor parameters_schema must be a mapping")
        if not isinstance(self.effect, ToolEffect):
            raise TypeError("tool descriptor effect must be ToolEffect")
        if not isinstance(self.origin, ToolOrigin):
            raise TypeError("tool descriptor origin must be ToolOrigin")
        if not isinstance(self.rule_configurable, bool):
            raise TypeError("tool descriptor rule_configurable must be bool")
        if self.origin is ToolOrigin.MCP and self.effect is not ToolEffect.EXTERNAL:
            raise ValueError("MCP tools must use the external effect")
        if self.origin is ToolOrigin.MCP and self.rule_configurable:
            raise ValueError("MCP tools cannot be rule configurable")


class DescriptorBackedTool:
    descriptor: ToolDescriptor

    @property
    def name(self) -> str:
        return self.descriptor.name

    @property
    def description(self) -> str:
        return self.descriptor.description

    @property
    def parameters_schema(self) -> Mapping[str, Any]:
        return self.descriptor.parameters_schema

    @property
    def origin(self) -> ToolOrigin:
        return self.descriptor.origin

    @property
    def requires_confirmation(self) -> bool:
        return self.descriptor.effect is not ToolEffect.READ

@dataclass(frozen=True)
class ToolEnvironment:
    path_policy: AllowedPathPolicy
    command_timeout_seconds: float = 10.0
    default_cwd: Path | None = None
    seatbelt: SeatbeltSession | None = None
    artifact_store: Any | None = None


@dataclass(frozen=True)
class ToolRunContext:
    environment: ToolEnvironment
    mode: AgentMode
    permission: PermissionSnapshot

    @property
    def path_policy(self):
        return self.environment.path_policy

    @property
    def command_timeout_seconds(self) -> float:
        return self.environment.command_timeout_seconds

    @property
    def default_cwd(self) -> Path | None:
        return self.environment.default_cwd

    @property
    def seatbelt(self) -> SeatbeltSession | None:
        return self.environment.seatbelt

    @property
    def artifact_store(self) -> Any | None:
        return self.environment.artifact_store

    @property
    def shell_policy(self) -> ShellPolicy:
        return self.permission.shell_policy

    @property
    def permission_state(self) -> PermissionSnapshot:
        return self.permission


@dataclass(frozen=True)
class ToolExecutionContext:
    path_policy: AllowedPathPolicy
    command_timeout_seconds: float = 10.0
    default_cwd: Path | None = None
    shell_policy: ShellPolicy = ShellPolicy.UNSANDBOXED_ASK
    seatbelt: SeatbeltSession | None = None
    permission_state: PermissionState | None = None
    artifact_store: Any | None = None

    def to_environment(self) -> ToolEnvironment:
        return ToolEnvironment(
            path_policy=self.path_policy,
            command_timeout_seconds=self.command_timeout_seconds,
            default_cwd=self.default_cwd,
            seatbelt=self.seatbelt,
            artifact_store=self.artifact_store,
        )

    def to_run_context(
        self,
        mode: AgentMode,
        permission_state: PermissionState | None = None,
    ) -> ToolRunContext:
        state = permission_state or self.permission_state
        permission = (
            state.snapshot()
            if state is not None
            else PermissionSnapshot(PermissionState().mode, self.shell_policy)
        )
        return ToolRunContext(self.to_environment(), mode, permission)


@dataclass(frozen=True)
class ToolPreview:
    tool_name: str
    summary: str
    target: str
    requires_confirmation: bool


@dataclass(frozen=True)
class PreparedToolCall:
    tool: Tool
    arguments: dict[str, Any]
    preview: ToolPreview


class Tool(Protocol):
    descriptor: ToolDescriptor

    def prepare(
        self,
        arguments: dict[str, Any],
        context: ToolRunContext,
    ) -> PreparedToolCall | ToolResult:
        ...

    async def execute(
        self,
        prepared: PreparedToolCall,
        context: ToolRunContext,
    ) -> ToolResult:
        ...
