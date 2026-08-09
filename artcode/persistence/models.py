from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from artcode.agent.memory import PlanMemory
    from artcode.conversation import ConversationContext


class InstructionScope(StrEnum):
    PROJECT_LOCAL = "project_local"
    PROJECT_ROOT = "project_root"
    USER = "user"


@dataclass(frozen=True)
class InstructionDocument:
    scope: InstructionScope
    path: Path
    content: str
    byte_count: int
    included_paths: tuple[Path, ...] = ()


@dataclass(frozen=True)
class InstructionIssue:
    source: Path
    code: str
    message: str


@dataclass(frozen=True)
class InstructionBundle:
    documents: tuple[InstructionDocument, ...] = ()
    total_bytes: int = 0
    issues: tuple[InstructionIssue, ...] = ()


@dataclass(frozen=True)
class SessionRecord:
    version: int
    timestamp: datetime
    entry_id: str
    mode: str
    message: dict[str, Any]


@dataclass(frozen=True)
class SessionDescriptor:
    session_id: str
    path: Path
    title: str
    message_count: int
    last_active_at: datetime
    bad_line_count: int = 0
    locked: bool = False


@dataclass(frozen=True)
class SessionRecoveryReport:
    descriptor: SessionDescriptor
    records: tuple[SessionRecord, ...]
    bad_line_count: int = 0
    truncated: bool = False
    truncated_reason: str = ""
    gap_reminder_required: bool = False
    recovered_plan: str | None = None
    issues: tuple[str, ...] = ()


@dataclass(frozen=True)
class CleanupReport:
    deleted: tuple[str, ...] = ()
    locked: tuple[str, ...] = ()
    failed: tuple[str, ...] = ()


class SessionSelectionMode(StrEnum):
    DEFAULT = "default"
    NEW = "new"
    RESUME = "resume"


@dataclass(frozen=True)
class SessionSelection:
    mode: SessionSelectionMode = SessionSelectionMode.DEFAULT
    session_id: str | None = None

    @classmethod
    def latest(cls) -> "SessionSelection":
        return cls(SessionSelectionMode.DEFAULT)

    @classmethod
    def new(cls) -> "SessionSelection":
        return cls(SessionSelectionMode.NEW)

    @classmethod
    def resume(cls, session_id: str) -> "SessionSelection":
        return cls(SessionSelectionMode.RESUME, session_id)


@dataclass(frozen=True)
class SessionContext:
    """The complete, session-owned state returned by :class:`SessionService`."""

    conversation: "ConversationContext"
    plan_memory: "PlanMemory"
    status: "PersistenceStatus"
    resume_reminder_required: bool = False


class MemoryScope(StrEnum):
    USER = "user"
    PROJECT = "project"


class MemoryCategory(StrEnum):
    PREFERENCE = "preference"
    CORRECTION = "correction"
    PROJECT_KNOWLEDGE = "project_knowledge"
    REFERENCE = "reference"


class MemoryStatus(StrEnum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"


@dataclass(frozen=True)
class MemoryNote:
    id: str
    scope: MemoryScope
    category: MemoryCategory
    status: MemoryStatus
    title: str
    summary: str
    body: str
    created_at: datetime
    updated_at: datetime
    source_session: str
    source_entry_ids: tuple[str, ...]


@dataclass(frozen=True)
class MemoryOperation:
    action: str
    scope: MemoryScope
    category: MemoryCategory
    target_id: str | None = None
    title: str = ""
    summary: str = ""
    body: str = ""
    source_entry_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class MemoryUpdateReport:
    status: str
    created: int = 0
    updated: int = 0
    superseded: int = 0
    rejected: int = 0
    message: str = ""


@dataclass(frozen=True)
class MemoryIndexReport:
    active_count: int = 0
    superseded_count: int = 0
    issue_count: int = 0
    omitted_count: int = 0
    byte_count: int = 0
    line_count: int = 0


@dataclass(frozen=True)
class MemoryScanReport:
    notes: tuple[MemoryNote, ...] = ()
    issues: tuple[str, ...] = ()


@dataclass(frozen=True)
class PersistenceStatus:
    session_id: str
    restored: bool
    recovered_messages: int = 0
    bad_line_count: int = 0
    truncated: bool = False
    truncated_reason: str = ""
    instruction_bytes: int = 0
    instruction_issues: int = 0
    user_active_notes: int = 0
    project_active_notes: int = 0
    default_locked_new_session: bool = False


@dataclass(frozen=True)
class RestorePreparationReport:
    attempted: bool = False
    status: str = "not_needed"
    before_tokens: int = 0
    after_tokens: int = 0
    message: str = ""
