"""Public Subagent Interface for Role-driven process-local Tasks."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable

from .model import Model, ModelRequest, Usage
from .tool import Tool, ToolRun
from .workspace import Workspace, WorktreeHandoff


class SubagentKind(StrEnum):
    DEFINITION = "definition"
    FORK = "fork"


class TaskState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    LIMIT = "limit"
    CANCELLED = "cancelled"


class RoleSource(StrEnum):
    PROJECT = "project"
    USER = "user"
    BUILTIN = "builtin"
    EXTENSION = "extension"


@dataclass(frozen=True, slots=True)
class RoleSummary:
    name: str
    description: str
    source: RoleSource


@dataclass(frozen=True, slots=True)
class RoleDiagnostic:
    name: str
    source: RoleSource
    message: str


@dataclass(frozen=True, slots=True)
class RoleCatalogSnapshot:
    roles: tuple[RoleSummary, ...]
    diagnostics: tuple[RoleDiagnostic, ...]


@dataclass(frozen=True, slots=True)
class TaskRequest:
    kind: SubagentKind
    task: str
    role: str | None = None
    background: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.kind, SubagentKind):
            raise TypeError("kind must be SubagentKind")
        if not isinstance(self.task, str) or not 1 <= len(self.task.strip()) <= 20_000:
            raise ValueError("task 去除首尾空白后长度必须为 1～20000。")
        if self.kind is SubagentKind.DEFINITION and not self.role:
            raise ValueError("definition Subagent 必须提供 Role。")
        if self.kind is SubagentKind.FORK and not self.background:
            raise ValueError("fork Subagent 必须在后台运行。")


@dataclass(frozen=True, slots=True)
class ParentRunSnapshot:
    prompt: ModelRequest
    tools: ToolRun


@dataclass(frozen=True, slots=True)
class TaskSnapshot:
    id: str
    kind: SubagentKind
    task: str
    role: str | None
    state: TaskState
    background: bool
    created_at: float
    started_at: float | None = None
    finished_at: float | None = None
    rounds: int = 0
    usage: Usage = Usage()
    result: str = ""
    permission_events: tuple[str, ...] = ()
    handoff: WorktreeHandoff | None = None


@dataclass(frozen=True, slots=True)
class TaskNotification:
    task_id: str
    state: TaskState
    result: str
    usage: Usage
    handoff: WorktreeHandoff | None
    truncated: bool = False


class ModelFactory(Protocol):
    def __call__(self, model: str | None) -> Model: ...


@runtime_checkable
class Subagent(Protocol):
    def refresh_roles(self) -> RoleCatalogSnapshot: ...

    def submit(self, request: TaskRequest, parent: ParentRunSnapshot) -> TaskSnapshot: ...

    def list(self) -> tuple[TaskSnapshot, ...]: ...

    def get(self, task_id: str) -> TaskSnapshot: ...

    async def wait(self, task_id: str) -> TaskSnapshot: ...

    async def cancel(self, task_id: str) -> TaskSnapshot: ...

    def take_notifications(self) -> tuple[TaskNotification, ...]: ...

    async def close(self) -> None: ...


__all__ = [
    "ModelFactory",
    "ParentRunSnapshot",
    "RoleCatalogSnapshot",
    "RoleDiagnostic",
    "RoleSource",
    "RoleSummary",
    "Subagent",
    "SubagentKind",
    "TaskNotification",
    "TaskRequest",
    "TaskSnapshot",
    "TaskState",
]
