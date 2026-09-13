from __future__ import annotations

from pathlib import Path
import subprocess
import time

import pytest

from artcode._workspace import LocalWorkspace


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(("git", *args), cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def repository(root: Path) -> Path:
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "user.name", "ArtCode Tests")
    git(root, "config", "user.email", "artcode@example.invalid")
    (root / ".gitignore").write_text(".artcode/worktrees/\n", encoding="utf-8")
    (root / "file.txt").write_text("base", encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-qm", "initial")
    return root


def test_inspection_failure_retains_worktree(tmp_path: Path) -> None:
    root = repository(tmp_path / "repo")
    scope = LocalWorkspace(root)
    lease = scope.acquire_worktree("task-00000001", scope.freeze_worktree())
    (lease.path / ".git").rename(lease.path / ".git-hidden")

    handoff = scope.release_worktree(lease)

    assert handoff.retained is True
    assert handoff.inspection_error
    assert lease.path.exists()


def test_cleanup_never_adopts_user_worktree_or_removes_active_lease(tmp_path: Path) -> None:
    root = repository(tmp_path / "repo")
    manual = tmp_path / "manual"
    git(root, "worktree", "add", "-q", "-b", "manual-branch", str(manual), "HEAD")
    scope = LocalWorkspace(root, clock=lambda: time.time() + 3 * 24 * 3600)
    lease = scope.acquire_worktree("task-00000001", scope.freeze_worktree())

    removed = scope.cleanup_worktrees(active_task_ids={lease.task_id}, max_age_seconds=1)

    assert removed == ()
    assert manual.exists()
    assert lease.path.exists()


def test_managed_root_symlink_is_rejected_without_touching_target(tmp_path: Path) -> None:
    root = repository(tmp_path / "repo")
    outside = tmp_path / "outside"
    outside.mkdir()
    managed = root / ".artcode" / "worktrees"
    managed.parent.mkdir()
    managed.symlink_to(outside, target_is_directory=True)
    scope = LocalWorkspace(root)

    with pytest.raises(ValueError, match="符号链接"):
        scope.acquire_worktree("task-00000001", scope.freeze_worktree())
    assert list(outside.iterdir()) == []
