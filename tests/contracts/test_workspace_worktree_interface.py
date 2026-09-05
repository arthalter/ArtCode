from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from artcode._workspace import LocalWorkspace
from artcode.core.workspace import DiscardConfirmation


def git(cwd: Path, *args: str) -> str:
    result = subprocess.run(("git", *args), cwd=cwd, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def repository(root: Path) -> Path:
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "user.name", "ArtCode Tests")
    git(root, "config", "user.email", "artcode@example.invalid")
    (root / ".gitignore").write_text(".artcode/worktrees/\n", encoding="utf-8")
    (root / "shared.txt").write_text("baseline", encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-qm", "initial")
    return root


def test_worktree_plan_freezes_baseline_and_excludes_main_dirty_state(tmp_path: Path) -> None:
    root = repository(tmp_path / "repo")
    scope = LocalWorkspace(root)
    plan = scope.freeze_worktree()
    (root / "shared.txt").write_text("dirty main", encoding="utf-8")
    (root / "untracked.txt").write_text("main only", encoding="utf-8")

    lease = scope.acquire_worktree("task-00000001", plan)

    assert lease.baseline == plan.baseline
    assert git(lease.path, "rev-parse", "HEAD") == plan.baseline
    assert (lease.path / "shared.txt").read_text(encoding="utf-8") == "baseline"
    assert not (lease.path / "untracked.txt").exists()


def test_clean_release_removes_worktree_but_dirty_release_retains成果(tmp_path: Path) -> None:
    root = repository(tmp_path / "repo")
    scope = LocalWorkspace(root)
    plan = scope.freeze_worktree()
    clean = scope.acquire_worktree("task-00000001", plan)
    dirty = scope.acquire_worktree("task-00000002", plan)
    (dirty.path / "result.txt").write_text("成果", encoding="utf-8")

    clean_handoff = scope.release_worktree(clean)
    dirty_handoff = scope.release_worktree(dirty)

    assert clean_handoff.retained is False
    assert not clean.path.exists()
    assert dirty_handoff.retained is True
    assert dirty_handoff.untracked_changes == 1
    assert (dirty.path / "result.txt").read_text(encoding="utf-8") == "成果"


def test_new_commit_is_retained_and_never_automatically_pushed_or_merged(tmp_path: Path) -> None:
    root = repository(tmp_path / "repo")
    scope = LocalWorkspace(root)
    lease = scope.acquire_worktree("task-00000001", scope.freeze_worktree())
    git(lease.path, "config", "user.name", "ArtCode Tests")
    git(lease.path, "config", "user.email", "artcode@example.invalid")
    (lease.path / "result.txt").write_text("done", encoding="utf-8")
    git(lease.path, "add", "result.txt")
    git(lease.path, "commit", "-qm", "result")

    handoff = scope.release_worktree(lease)

    assert handoff.retained is True
    assert handoff.commits_ahead == 1
    assert handoff.all_commits_pushed is False
    assert git(root, "branch", "--show-current") != lease.branch


def test_dangerous_discard_requires_exact_inactive_lease_confirmation(tmp_path: Path) -> None:
    root = repository(tmp_path / "repo")
    scope = LocalWorkspace(root)
    lease = scope.acquire_worktree("task-00000001", scope.freeze_worktree())
    (lease.path / "result.txt").write_text("成果", encoding="utf-8")

    with pytest.raises(ValueError, match="活动"):
        scope.discard_worktree(
            lease,
            DiscardConfirmation(lease.task_id, str(lease.path), lease.branch),
        )
    scope.release_worktree(lease)
    with pytest.raises(ValueError, match="精确"):
        scope.discard_worktree(
            lease,
            DiscardConfirmation(lease.task_id, str(lease.path), "wrong-branch"),
        )

    scope.discard_worktree(
        lease,
        DiscardConfirmation(lease.task_id, str(lease.path), lease.branch),
    )
    assert not lease.path.exists()


def test_non_git_workspace_fails_without_initializing_repository(tmp_path: Path) -> None:
    root = tmp_path / "plain"
    root.mkdir()
    scope = LocalWorkspace(root)

    with pytest.raises(ValueError, match="Git"):
        scope.freeze_worktree()
    assert not (root / ".git").exists()


def test_default_initialization_copies_local_files_links_dependency_and_sets_hooks(tmp_path: Path) -> None:
    root = repository(tmp_path / "repo")
    (root / ".gitignore").write_text(
        ".artcode/worktrees/\n.artcode/instructions.md\npermissions.local.yml\n.venv/\n",
        encoding="utf-8",
    )
    (root / "permissions.local.yml").write_text("local", encoding="utf-8")
    (root / ".artcode").mkdir()
    (root / ".artcode/instructions.md").write_text("instructions", encoding="utf-8")
    (root / ".venv").mkdir()
    (root / ".venv/dependency.txt").write_text("dependency", encoding="utf-8")
    (root / ".githooks").mkdir()
    (root / ".githooks/pre-commit").write_text("#!/bin/sh\n", encoding="utf-8")
    git(root, "add", ".gitignore", ".githooks/pre-commit")
    git(root, "commit", "-qm", "worktree setup")
    scope = LocalWorkspace(root)

    lease = scope.acquire_worktree("task-00000001", scope.freeze_worktree())
    child = scope.open_worktree(lease)

    assert (lease.path / "permissions.local.yml").read_text(encoding="utf-8") == "local"
    assert (lease.path / ".artcode/instructions.md").read_text(encoding="utf-8") == "instructions"
    assert (lease.path / ".venv").is_symlink()
    assert git(lease.path, "config", "--worktree", "core.hooksPath") == str(lease.path / ".githooks")
    assert child.read_text(child.prepare_target(".venv/dependency.txt", must_exist=True)).text == "dependency"
    with pytest.raises(Exception, match="只读"):
        child.write_text(
            child.prepare_target(".venv/dependency.txt", must_exist=True),
            "changed",
            overwrite=True,
        )
    assert (root / ".venv/dependency.txt").read_text(encoding="utf-8") == "dependency"
    child.close()
    handoff = scope.release_worktree(lease)
    assert handoff.retained is False


def test_initialization_rules_are_frozen_with_worktree_plan(tmp_path: Path) -> None:
    root = repository(tmp_path / "repo")
    (root / ".gitignore").write_text(".artcode/worktrees/\nfirst.env\nsecond.env\n", encoding="utf-8")
    (root / "first.env").write_text("first", encoding="utf-8")
    (root / "second.env").write_text("second", encoding="utf-8")
    rules = root / ".artcode/worktree.yml"
    rules.parent.mkdir()
    rules.write_text("version: 1\ncopy: [first.env]\nsymlink: []\nhooks: null\n", encoding="utf-8")
    scope = LocalWorkspace(root)
    plan = scope.freeze_worktree()
    rules.write_text("version: 1\ncopy: [second.env]\nsymlink: []\nhooks: null\n", encoding="utf-8")

    lease = scope.acquire_worktree("task-00000001", plan)

    assert (lease.path / "first.env").read_text(encoding="utf-8") == "first"
    assert not (lease.path / "second.env").exists()
    assert scope.release_worktree(lease).retained is False
