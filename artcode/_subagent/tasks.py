from __future__ import annotations

from dataclasses import dataclass, field
import asyncio
import time
from typing import Callable

from artcode.core.model import Usage
from artcode.core.subagent import SubagentKind, TaskSnapshot, TaskState
from artcode.core.workspace import WorktreeHandoff, WorktreePlan


@dataclass
class TaskRecord:
    id: str
    kind: SubagentKind
    task: str
    role: str | None
    background: bool
    created_at: float
    state: TaskState = TaskState.QUEUED
    started_at: float | None = None
    finished_at: float | None = None
    rounds: int = 0
    usage: Usage = Usage()
    result: str = ""
    permission_events: list[str] = field(default_factory=list)
    handoff: WorktreeHandoff | None = None
    worktree_plan: WorktreePlan | None = None
    runner: object | None = None
    notified: bool = False
    background_event: asyncio.Event = field(default_factory=asyncio.Event)

    def snapshot(self) -> TaskSnapshot:
        return TaskSnapshot(
            self.id,
            self.kind,
            self.task,
            self.role,
            self.state,
            self.background,
            self.created_at,
            self.started_at,
            self.finished_at,
            self.rounds,
            self.usage,
            self.result,
            tuple(self.permission_events),
            self.handoff,
        )
