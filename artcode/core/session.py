"""Public Session Interface and immutable Transcript facts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, TypeAlias, runtime_checkable

from .model import Model, ModelRequest, ProtocolMetadata, ToolRequest, Usage
from .tool import RunMode, ToolResult, ToolRun


class SessionFailure(RuntimeError):
    pass


class SessionBusy(SessionFailure):
    pass


class SessionCorrupt(SessionFailure):
    pass


class SelectionKind(StrEnum):
    NEW = "new"
    LATEST = "latest"
    EXACT = "exact"


@dataclass(frozen=True, slots=True)
class SessionSelection:
    kind: SelectionKind
    session_id: str | None = None

    @classmethod
    def new(cls) -> SessionSelection:
        return cls(SelectionKind.NEW)

    @classmethod
    def latest(cls) -> SessionSelection:
        return cls(SelectionKind.LATEST)

    @classmethod
    def exact(cls, session_id: str) -> SessionSelection:
        return cls(SelectionKind.EXACT, session_id)

    def __post_init__(self) -> None:
        if self.kind is SelectionKind.EXACT and not self.session_id:
            raise ValueError("精确 Session 选择需要 session_id。")
        if self.kind is not SelectionKind.EXACT and self.session_id is not None:
            raise ValueError("只有精确 Session 选择可以携带 session_id。")


class AssistantCompletion(StrEnum):
    NATURAL = "natural"
    LENGTH = "length"


class RunCompletion(StrEnum):
    NATURAL = "natural"
    LENGTH = "length"
    CANCELLED = "cancelled"
    FAILED = "failed"
    LIMIT = "limit"


class CompactionTrigger(StrEnum):
    AUTOMATIC = "automatic"
    FORCED = "forced"
    EMERGENCY = "emergency"
    MANUAL = "manual"


@dataclass(frozen=True, slots=True)
class RunContribution:
    name: str
    instructions: str
    model: str | None = None


@dataclass(frozen=True, slots=True)
class PromptBudget:
    tokens: int
    source: str


@dataclass(frozen=True, slots=True)
class RunLease:
    id: str
    goal: str
    mode: RunMode
    tools: ToolRun
    prompt_preview: ModelRequest
    pending_notices: tuple[tuple[str, str], ...]
    transcript_size: int
    budget: PromptBudget


@dataclass(frozen=True, slots=True)
class DispatchedRun:
    lease: RunLease
    request: ModelRequest


@dataclass(frozen=True, slots=True)
class CompactionReport:
    trigger: CompactionTrigger
    status: str
    summarized_facts: int = 0
    detail: str = ""


@dataclass(frozen=True, slots=True)
class MemoryReport:
    status: str
    user_preferences_added: int = 0
    project_facts_added: int = 0
    detail: str = ""


@dataclass(frozen=True, slots=True)
class UserFact:
    text: str


@dataclass(frozen=True, slots=True)
class AssistantFact:
    text: str
    completion: AssistantCompletion


@dataclass(frozen=True, slots=True)
class ToolExchangeFact:
    requests: tuple[ToolRequest, ...]
    results: tuple[ToolResult, ...]
    metadata: ProtocolMetadata | None = None
    assistant_text: str = ""


TranscriptFact: TypeAlias = UserFact | AssistantFact | ToolExchangeFact


@dataclass(frozen=True, slots=True)
class SessionSnapshot:
    session_id: str
    created_at: float
    restored: bool
    facts: tuple[TranscriptFact, ...]
    recovery_issues: tuple[str, ...] = ()
    latest_plan: str | None = None
    pending_notices: tuple[str, ...] = ()
    summary_active: bool = False
    last_usage: Usage | None = None
    memory_pending: int = 0
    last_memory_report: MemoryReport | None = None


@runtime_checkable
class Session(Protocol):
    def snapshot(self) -> SessionSnapshot: ...

    def commit_user(self, text: str) -> SessionSnapshot: ...

    def commit_assistant(
        self, text: str, completion: AssistantCompletion
    ) -> SessionSnapshot: ...

    def commit_tool_exchange(
        self,
        requests: tuple[ToolRequest, ...],
        results: tuple[ToolResult, ...],
        *,
        metadata: ProtocolMetadata | None = None,
        cancelled: bool = False,
        assistant_text: str = "",
    ) -> SessionSnapshot: ...

    def add_notice(self, text: str) -> SessionSnapshot: ...

    async def prepare_run(
        self,
        goal: str,
        tools: ToolRun,
        *,
        contributions: tuple[RunContribution, ...] = (),
        model_for_compaction: Model | None = None,
        frozen_prompt: ModelRequest | None = None,
    ) -> RunLease: ...

    def dispatch_run(self, lease: RunLease) -> DispatchedRun: ...

    def finish_run(
        self,
        lease: RunLease,
        completion: RunCompletion,
        *,
        assistant_text: str = "",
        usage: Usage | None = None,
    ) -> SessionSnapshot: ...

    async def compact(
        self, model: Model, trigger: CompactionTrigger
    ) -> CompactionReport: ...

    def schedule_memory_update(
        self,
        lease: RunLease,
        completion: RunCompletion,
        assistant_text: str,
        model: Model,
    ) -> bool: ...

    async def wait_memory_idle(self) -> None: ...

    async def aclose(self) -> None: ...

    def close(self) -> None: ...


__all__ = [
    "AssistantCompletion",
    "AssistantFact",
    "CompactionReport",
    "CompactionTrigger",
    "DispatchedRun",
    "MemoryReport",
    "PromptBudget",
    "RunCompletion",
    "RunContribution",
    "RunLease",
    "SelectionKind",
    "Session",
    "SessionBusy",
    "SessionCorrupt",
    "SessionFailure",
    "SessionSelection",
    "SessionSnapshot",
    "ToolExchangeFact",
    "TranscriptFact",
    "UserFact",
]
