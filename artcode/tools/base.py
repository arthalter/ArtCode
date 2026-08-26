from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping, Protocol

from artcode.permissions import PermissionSnapshot, ShellPolicy
from artcode.sandbox import SeatbeltSession
from artcode.workspace import Workspace

from .policy import WorkspacePathPolicy
from .results import ToolResult

if TYPE_CHECKING:
    from artcode.agent.modes import AgentMode


class ToolOrigin(StrEnum):
    BUILTIN = "builtin"
    MCP = "mcp"
    SYSTEM = "system"


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
    subagent_allowed: bool = False

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
        if not isinstance(self.subagent_allowed, bool):
            raise TypeError("tool descriptor subagent_allowed must be bool")
        if self.origin is ToolOrigin.MCP and self.effect is not ToolEffect.EXTERNAL:
            raise ValueError("MCP tools must use the external effect")
        if self.origin is ToolOrigin.MCP and self.rule_configurable:
            raise ValueError("MCP tools cannot be rule configurable")
        if self.origin is ToolOrigin.SYSTEM and self.rule_configurable:
            raise ValueError("system tools cannot be rule configurable")


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

@dataclass(frozen=True)
class ToolEnvironment:
    path_policy: WorkspacePathPolicy
    command_timeout_seconds: float = 10.0
    default_cwd: Path | None = None
    seatbelt: SeatbeltSession | None = None
    artifact_store: Any | None = None
    file_cache: Any | None = None
    agent_id: str = "main"
    is_subagent: bool = False

    @classmethod
    def from_workspace(
        cls,
        workspace: Workspace | Path,
        *,
        sensitive_paths: tuple[Path, ...] = (),
        command_timeout_seconds: float = 10.0,
        seatbelt: SeatbeltSession | None = None,
        artifact_store: Any | None = None,
    ) -> "ToolEnvironment":
        selected = (
            workspace
            if isinstance(workspace, Workspace)
            else Workspace.from_path(workspace)
        )
        from .file_cache import FileReadCache

        return cls(
            WorkspacePathPolicy(selected, sensitive_paths),
            command_timeout_seconds,
            selected.root,
            seatbelt,
            artifact_store,
            FileReadCache(),
        )


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

    @property
    def is_subagent(self) -> bool:
        return self.environment.is_subagent


@dataclass(frozen=True)
class ToolPreview:
    tool_name: str
    summary: str
    target: str


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
