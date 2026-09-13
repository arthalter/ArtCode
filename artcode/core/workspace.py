"""The public Workspace Interface.

Callers prepare an immutable target before asking for an effect.  Concrete
filesystem, process, Seatbelt, and Git adapters remain private to the Workspace
module; later tasks extend this same Interface without exposing those details.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol, runtime_checkable


class WorkspaceFailure(OSError):
    """Base class for deterministic Workspace failures."""

    code = "workspace_failure"


class PathOutsideWorkspace(WorkspaceFailure):
    code = "path_outside_workspace"


class SensitivePath(WorkspaceFailure):
    code = "sensitive_path"


class TargetChanged(WorkspaceFailure):
    code = "target_changed"


class AtomicWriteFailure(WorkspaceFailure):
    code = "atomic_write_failure"


class SeatbeltUnavailable(WorkspaceFailure):
    code = "seatbelt_unavailable"


class IsolationMode(str, Enum):
    ENFORCED = "enforced"
    EXPLICIT_UNSAFE = "explicit_unsafe"


@dataclass(frozen=True, slots=True)
class ProcessRequest:
    argv: tuple[str, ...]
    cwd: str = "."
    environment: tuple[tuple[str, str], ...] = ()
    timeout_seconds: float = 120.0
    isolation: IsolationMode = IsolationMode.ENFORCED


@dataclass(frozen=True, slots=True)
class ProcessOutcome:
    argv: tuple[str, ...]
    returncode: int | None
    stdout: str
    stderr: str
    timed_out: bool = False
    cancelled: bool = False
    start_error: str | None = None
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    stdout_reference: str | None = None
    stderr_reference: str | None = None


@dataclass(frozen=True, slots=True)
class WorktreePlan:
    baseline: str


@dataclass(frozen=True, slots=True)
class WorktreeLease:
    task_id: str
    name: str
    path: Path
    branch: str
    baseline: str
    created_at: float
    initialization_paths: tuple[str, ...] = ()
    readable_paths: tuple[Path, ...] = ()


@dataclass(frozen=True, slots=True)
class WorktreeHandoff:
    task_id: str
    baseline: str
    branch: str
    path: Path
    retained: bool
    tracked_changes: int
    staged_changes: int
    untracked_changes: int
    commits_ahead: int
    has_upstream: bool
    all_commits_pushed: bool
    inspection_error: str = ""


@dataclass(frozen=True, slots=True)
class DiscardConfirmation:
    task_id: str
    path: str
    branch: str


@dataclass(frozen=True, slots=True)
class TargetSnapshot:
    """An auditable, immutable target prepared for a later operation."""

    scope_id: str
    path: str
    must_exist: bool


@dataclass(frozen=True, slots=True)
class TextSlice:
    text: str
    start_line: int
    end_line: int
    total_lines: int
    truncated: bool
    next_line: int | None


@dataclass(frozen=True, slots=True)
class FileChange:
    path: str
    created: bool
    bytes_written: int


@dataclass(frozen=True, slots=True)
class FileList:
    paths: tuple[str, ...]
    truncated: bool


@dataclass(frozen=True, slots=True)
class TextMatch:
    path: str
    line: int
    text: str


@dataclass(frozen=True, slots=True)
class SearchResult:
    matches: tuple[TextMatch, ...]
    truncated: bool
    skipped_unreadable: int


@dataclass(frozen=True, slots=True)
class StoredResult:
    reference: str
    preview: str
    original_bytes: int
    truncated: bool


@runtime_checkable
class Workspace(Protocol):
    """All local effects for one explicit Workspace scope."""

    @property
    def root(self) -> Path: ...

    @property
    def scope_id(self) -> str: ...

    @property
    def active_process_count(self) -> int: ...

    def prepare_target(self, path: str | Path, *, must_exist: bool) -> TargetSnapshot: ...

    def read_text(
        self,
        target: TargetSnapshot,
        *,
        start_line: int | None = None,
        end_line: int | None = None,
    ) -> TextSlice: ...

    def write_text(
        self,
        target: TargetSnapshot,
        content: str,
        *,
        overwrite: bool,
    ) -> FileChange: ...

    def edit_text(self, target: TargetSnapshot, old_text: str, new_text: str) -> FileChange: ...

    def find_files(self, pattern: str, *, limit: int = 1000) -> FileList: ...

    def search_text(
        self,
        query: str,
        *,
        glob: str = "**/*",
        limit: int = 1000,
    ) -> SearchResult: ...

    def store_result(self, source: str, content: str) -> StoredResult: ...

    def read_result(self, reference: str, *, start_line: int, end_line: int) -> TextSlice: ...

    async def run_process(self, request: ProcessRequest) -> ProcessOutcome: ...

    def freeze_worktree(self) -> WorktreePlan: ...

    def acquire_worktree(
        self, task_id: str, plan: WorktreePlan, *, name: str | None = None
    ) -> WorktreeLease: ...

    def open_worktree(self, lease: WorktreeLease) -> Workspace: ...

    def inspect_worktree(self, lease: WorktreeLease) -> WorktreeHandoff: ...

    def release_worktree(self, lease: WorktreeLease) -> WorktreeHandoff: ...

    def cleanup_worktrees(
        self, *, active_task_ids: set[str], max_age_seconds: float = 86_400
    ) -> tuple[str, ...]: ...

    def discard_worktree(
        self, lease: WorktreeLease, confirmation: DiscardConfirmation
    ) -> None: ...

    def find_worktree(self, task_id: str) -> WorktreeLease | None: ...

    def list_managed_worktrees(self) -> tuple[WorktreeHandoff, ...]: ...

    async def aclose(self) -> None: ...

    def close(self) -> None: ...


__all__ = [
    "AtomicWriteFailure",
    "DiscardConfirmation",
    "FileChange",
    "FileList",
    "IsolationMode",
    "PathOutsideWorkspace",
    "ProcessOutcome",
    "ProcessRequest",
    "SearchResult",
    "SensitivePath",
    "SeatbeltUnavailable",
    "StoredResult",
    "TargetChanged",
    "TargetSnapshot",
    "TextMatch",
    "TextSlice",
    "Workspace",
    "WorkspaceFailure",
    "WorktreeHandoff",
    "WorktreeLease",
    "WorktreePlan",
]
