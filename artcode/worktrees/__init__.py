"""Safe, managed Git worktrees for file-writing sub-agents."""

from .manager import WorktreeManager
from .cleanup import WorktreeCleanupService
from .models import WorktreeHandoff, WorktreeLease, WorktreeStatus
from .naming import WorktreeName, make_system_name, validate_worktree_name

__all__ = [
    "WorktreeHandoff",
    "WorktreeLease",
    "WorktreeManager",
    "WorktreeCleanupService",
    "WorktreeName",
    "WorktreeStatus",
    "make_system_name",
    "validate_worktree_name",
]
