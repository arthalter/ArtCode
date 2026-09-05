"""Public Application Interface and user-visible events."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from collections.abc import AsyncIterator
from typing import Any, Protocol, TypeAlias, runtime_checkable

from .session import SessionSelection, SessionSnapshot
from .skill import SkillSnapshot
from .subagent import TaskSnapshot
from .tool import ApprovalRequest, McpServerApprover, PermissionSnapshot
from .workspace import WorktreeHandoff


@dataclass(frozen=True, slots=True)
class ApplicationOptions:
    workspace: Path
    config_path: Path
    artcode_home: Path
    session: SessionSelection


@dataclass(frozen=True, slots=True)
class ApplicationSnapshot:
    workspace: Path
    session: SessionSnapshot
    permission: PermissionSnapshot
    skills: SkillSnapshot
    tasks: tuple[TaskSnapshot, ...]
    running: bool
    closed: bool


@dataclass(frozen=True, slots=True)
class TextOutput:
    text: str
    streaming: bool = False


@dataclass(frozen=True, slots=True)
class ErrorOutput:
    message: str


@dataclass(frozen=True, slots=True)
class StateOutput:
    name: str
    value: Any


@dataclass(frozen=True, slots=True)
class RunStopped:
    reason: str
    rounds: int


@dataclass(frozen=True, slots=True)
class ClearDisplay:
    pass


@dataclass(frozen=True, slots=True)
class ExitRequested:
    code: int = 0


ApplicationEvent: TypeAlias = TextOutput | ErrorOutput | StateOutput | RunStopped | ClearDisplay | ExitRequested


class Interaction(Protocol):
    async def approve(self, request: ApprovalRequest): ...

    async def approve_mcp_server(self, name: str, summary: str) -> bool: ...

    async def confirm_worktree_discard(self, handoff: WorktreeHandoff) -> bool: ...

    async def choose_active_task_exit(self, tasks: tuple[TaskSnapshot, ...]) -> str: ...


@runtime_checkable
class Application(Protocol):
    def stream(self, text: str) -> AsyncIterator[ApplicationEvent]: ...

    async def handle(self, text: str) -> tuple[ApplicationEvent, ...]: ...

    def snapshot(self) -> ApplicationSnapshot: ...

    def cancel_current(self) -> bool: ...

    def background_current_task(self) -> bool: ...

    async def close(self) -> None: ...


__all__ = [
    "Application",
    "ApplicationEvent",
    "ApplicationOptions",
    "ApplicationSnapshot",
    "ClearDisplay",
    "ErrorOutput",
    "ExitRequested",
    "Interaction",
    "RunStopped",
    "StateOutput",
    "TextOutput",
]
