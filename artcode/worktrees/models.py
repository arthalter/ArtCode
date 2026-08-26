from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class WorktreeLease:
    task_id: str
    name: str
    path: Path
    branch: str
    baseline: str
    main_workspace: Path
    metadata_path: Path
    created_at: float
    initialization_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class WorktreeStatus:
    tracked_changes: int
    staged_changes: int
    untracked_changes: int
    commits_ahead: int
    has_upstream: bool
    all_commits_pushed: bool
    inspection_error: str = ""

    @property
    def has_file_changes(self) -> bool:
        return bool(self.tracked_changes or self.staged_changes or self.untracked_changes)

    @property
    def safe_to_remove(self) -> bool:
        return (
            not self.inspection_error
            and not self.has_file_changes
            and self.commits_ahead == 0
        )


@dataclass(frozen=True)
class WorktreeHandoff:
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
    message: str = ""
