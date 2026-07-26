from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from artcode.permissions import PermissionState, ShellPolicy
from artcode.sandbox import SeatbeltSession

from .policy import AllowedPathPolicy
from .results import MAX_RESULT_BYTES, ToolResult


@dataclass(frozen=True)
class ToolExecutionContext:
    path_policy: AllowedPathPolicy
    max_result_bytes: int = MAX_RESULT_BYTES
    command_timeout_seconds: float = 10.0
    default_cwd: Path | None = None
    shell_policy: ShellPolicy = ShellPolicy.UNSANDBOXED_ASK
    seatbelt: SeatbeltSession | None = None
    permission_state: PermissionState | None = None


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
    name: str
    description: str
    parameters_schema: dict[str, Any]
    requires_confirmation: bool

    def prepare(
        self,
        arguments: dict[str, Any],
        context: ToolExecutionContext,
    ) -> PreparedToolCall | ToolResult:
        ...

    async def execute(
        self,
        prepared: PreparedToolCall,
        context: ToolExecutionContext,
    ) -> ToolResult:
        ...
