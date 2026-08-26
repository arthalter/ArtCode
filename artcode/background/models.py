from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from artcode.subagents.models import AgentCreateRequest, SubagentResult


class BackgroundTaskStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    MAX_ROUNDS = "max_rounds"
    CANCELLED = "cancelled"


_TERMINAL = frozenset(
    {BackgroundTaskStatus.COMPLETED, BackgroundTaskStatus.FAILED, BackgroundTaskStatus.MAX_ROUNDS, BackgroundTaskStatus.CANCELLED}
)
_TRANSITIONS = {
    BackgroundTaskStatus.QUEUED: frozenset({BackgroundTaskStatus.RUNNING, BackgroundTaskStatus.CANCELLED, BackgroundTaskStatus.FAILED}),
    BackgroundTaskStatus.RUNNING: frozenset(_TERMINAL),
    **{status: frozenset() for status in _TERMINAL},
}


def is_terminal(status: BackgroundTaskStatus) -> bool:
    return status in _TERMINAL


def ensure_transition(before: BackgroundTaskStatus, after: BackgroundTaskStatus) -> None:
    if after not in _TRANSITIONS[before]:
        raise ValueError(f"invalid background task transition: {before} -> {after}")


@dataclass(frozen=True)
class BackgroundTaskSummary:
    task_id: str
    kind: str
    role_name: str | None
    status: BackgroundTaskStatus
    background: bool
    queued_at: float
    started_at: float | None
    finished_at: float | None
    worktree_required: bool
    worktree_path: str | None = None
    worktree_retained: bool | None = None


@dataclass(frozen=True)
class BackgroundTaskDetail(BackgroundTaskSummary):
    request: AgentCreateRequest | None = None
    result: SubagentResult | None = None
    error_message: str = ""
    completion_index: int | None = None
