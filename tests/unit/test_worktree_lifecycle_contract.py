from __future__ import annotations

import os
import re
import subprocess
import asyncio
from pathlib import Path

import pytest

from artcode.worktrees import (
    WorktreeCleanupService,
    WorktreeManager,
    validate_worktree_name,
)
from artcode.worktrees.initializer import WorktreeInitRules, read_rules


def _git(root: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and result.returncode != 0:
        raise AssertionError(result.stderr)
    return result.stdout.strip()


def _repository(tmp_path: Path, *, clock=None) -> tuple[Path, WorktreeManager]:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "tests@example.com")
    _git(root, "config", "user.name", "Tests")
    (root / ".gitignore").write_text(
        ".artcode/worktrees/\n"
        ".artcode/instructions.md\n"
        "permissions.local.yml\n"
        ".venv/\n",
        encoding="utf-8",
    )
    (root / "tracked.txt").write_text("base\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "initial")
    return root, WorktreeManager(root, **({} if clock is None else {"clock": clock}))


@pytest.mark.parametrize(
    "name",
    (
        "",
        "/absolute",
        "~home",
        "upper/Bad",
        "a//b",
        "a/./b",
        "a/../b",
        "a\\b",
        "a\0b",
        "a\nb",
        "a" * 33,
        "a/" + "b" * 63,
        "中文",
    ),
)
def test_worktree_names_reject_unsafe_input_without_creating_root(
    tmp_path: Path, name: str
) -> None:
    managed = tmp_path / "not-created" / "worktrees"

    with pytest.raises(ValueError):
        validate_worktree_name(managed, name)

    assert not managed.exists()


def test_manual_nested_name_maps_to_branch_and_stays_inside_root(tmp_path: Path) -> None:
    root = tmp_path / "managed"

    selected = validate_worktree_name(root, "feature/review-1")

    assert selected.path == root / "feature" / "review-1"
    assert selected.branch == "worktree-feature/review-1"


def test_system_worktree_name_and_branch_are_stable_from_task_id(tmp_path: Path) -> None:
    root, manager = _repository(tmp_path)
    lease = manager.acquire("task-12ab34cd", manager.capture_baseline())

    assert lease.name == "agent-12ab34cd"
    assert lease.path == root / ".artcode" / "worktrees" / "agent-12ab34cd"
    assert lease.branch == "worktree-agent-12ab34cd"
    assert _git(lease.path, "rev-parse", "HEAD") == lease.baseline
    assert oct(lease.metadata_path.stat().st_mode & 0o777) == "0o600"


def test_fast_recovery_uses_only_trusted_files_and_no_git_process(tmp_path: Path) -> None:
    root, manager = _repository(tmp_path)
    baseline = manager.capture_baseline()
    original = manager.acquire("task-aabbccdd", baseline)
    recovered_manager = WorktreeManager(root)

    def forbidden_git(*_args, **_kwargs):
        raise AssertionError("fast recovery must not invoke git")

    recovered_manager._git = forbidden_git  # type: ignore[method-assign]
    recovered = recovered_manager.acquire("task-aabbccdd", baseline)

    assert recovered == original


def test_fast_recovery_rejects_unknown_untracked_file_without_mutating_it(
    tmp_path: Path,
) -> None:
    root, manager = _repository(tmp_path)
    baseline = manager.capture_baseline()
    lease = manager.acquire("task-abcdef12", baseline)
    intruder = lease.path / "unknown.txt"
    intruder.write_text("sentinel", encoding="utf-8")

    with pytest.raises(ValueError, match="未知普通文件"):
        WorktreeManager(root).acquire("task-abcdef12", baseline)

    assert intruder.read_text(encoding="utf-8") == "sentinel"


def test_default_initialization_copies_links_and_sets_worktree_only_hooks(
    tmp_path: Path,
) -> None:
    root, manager = _repository(tmp_path)
    (root / "permissions.local.yml").write_text("rules: []\n", encoding="utf-8")
    (root / ".artcode").mkdir(exist_ok=True)
    (root / ".artcode" / "instructions.md").write_text("LOCAL\n", encoding="utf-8")
    (root / ".venv").mkdir()
    (root / ".venv" / "marker").write_text("shared", encoding="utf-8")
    (root / ".githooks").mkdir()
    (root / ".githooks" / "pre-commit").write_text("#!/bin/sh\n", encoding="utf-8")
    _git(root, "add", ".githooks")
    _git(root, "commit", "-qm", "add hooks")

    lease = manager.acquire("task-10203040", manager.capture_baseline())

    assert (lease.path / "permissions.local.yml").read_text() == "rules: []\n"
    assert (lease.path / ".artcode" / "instructions.md").read_text() == "LOCAL\n"
    assert (lease.path / ".venv").is_symlink()
    assert (lease.path / ".venv").resolve() == (root / ".venv").resolve()
    assert _git(lease.path, "config", "--worktree", "--get", "core.hooksPath") == str(
        lease.path / ".githooks"
    )
    assert _git(root, "config", "--get", "core.hooksPath", check=False) == ""
    assert manager.status(lease).has_file_changes is False


def test_explicit_missing_initialization_item_rolls_back_new_worktree(
    tmp_path: Path,
) -> None:
    root, manager = _repository(tmp_path)
    baseline = manager.capture_baseline()

    with pytest.raises(ValueError, match="不存在"):
        manager.acquire(
            "task-fedcba98",
            baseline,
            rules=WorktreeInitRules(("missing.env",), (), None),
        )

    target = root / ".artcode" / "worktrees" / "agent-fedcba98"
    assert not target.exists()
    assert "worktree-agent-fedcba98" not in _git(root, "branch", "--format=%(refname:short)").splitlines()


def test_status_classifies_tracked_staged_and_untracked_separately(tmp_path: Path) -> None:
    _root, manager = _repository(tmp_path)
    lease = manager.acquire("task-11112222", manager.capture_baseline())
    (lease.path / "tracked.txt").write_text("changed\n", encoding="utf-8")
    (lease.path / "staged.txt").write_text("staged\n", encoding="utf-8")
    _git(lease.path, "add", "staged.txt")
    (lease.path / "untracked.txt").write_text("untracked\n", encoding="utf-8")

    status = manager.status(lease)

    assert status.tracked_changes == 1
    assert status.staged_changes == 1
    assert status.untracked_changes == 1
    assert status.commits_ahead == 0
    assert manager.handoff(lease).retained is True


def test_any_new_commit_is_retained_at_task_handoff(tmp_path: Path) -> None:
    _root, manager = _repository(tmp_path)
    lease = manager.acquire("task-33334444", manager.capture_baseline())
    (lease.path / "tracked.txt").write_text("committed\n", encoding="utf-8")
    _git(lease.path, "add", "tracked.txt")
    _git(lease.path, "commit", "-qm", "child commit")

    handoff = manager.handoff(lease)

    assert handoff.retained is True
    assert handoff.commits_ahead == 1
    assert handoff.has_upstream is False
    assert handoff.all_commits_pushed is False
    assert lease.path.exists()


def test_expired_clean_worktree_is_removed_with_branch_and_metadata(tmp_path: Path) -> None:
    now = [0.0]
    root, manager = _repository(tmp_path, clock=lambda: now[0])
    lease = manager.acquire("task-55556666", manager.capture_baseline())
    now[0] = 24 * 60 * 60 - 0.001
    assert WorktreeManager(root, clock=lambda: now[0]).cleanup_expired(()) == ()
    assert lease.path.exists()
    now[0] = 24 * 60 * 60

    removed = WorktreeManager(root, clock=lambda: now[0]).cleanup_expired(())

    assert removed == (lease.task_id,)
    assert not lease.path.exists()
    assert not lease.metadata_path.exists()
    assert lease.branch not in _git(root, "branch", "--format=%(refname:short)").splitlines()


async def test_cleanup_service_scans_at_startup_and_periodically() -> None:
    class FakeManager:
        def __init__(self) -> None:
            self.calls: list[tuple[tuple[str, ...], float]] = []

        def cleanup_expired(self, active, *, max_age_seconds):
            self.calls.append((tuple(active), max_age_seconds))
            return ()

    manager = FakeManager()
    service = WorktreeCleanupService(
        manager,  # type: ignore[arg-type]
        lambda: ("task-active1",),
        interval_seconds=0.01,
    )

    await service.start()
    await asyncio.sleep(0.03)
    await service.close()

    assert len(manager.calls) >= 2
    assert manager.calls[0] == (("task-active1",), 24 * 60 * 60)


def test_expired_dirty_or_unpushed_worktree_is_preserved(tmp_path: Path) -> None:
    now = [0.0]
    root, manager = _repository(tmp_path, clock=lambda: now[0])
    dirty = manager.acquire("task-77778888", manager.capture_baseline())
    (dirty.path / "tracked.txt").write_text("dirty\n", encoding="utf-8")
    committed = manager.acquire("task-9999aaaa", manager.capture_baseline())
    (committed.path / "tracked.txt").write_text("commit\n", encoding="utf-8")
    _git(committed.path, "add", "tracked.txt")
    _git(committed.path, "commit", "-qm", "local only")
    now[0] = 24 * 60 * 60
    scanner = WorktreeManager(root, clock=lambda: now[0])

    assert scanner.cleanup_expired(()) == ()
    assert dirty.path.exists() and committed.path.exists()
    assert any("未提交" in item for item in scanner.last_cleanup_diagnostics)
    assert any("未安全交接" in item for item in scanner.last_cleanup_diagnostics)


def test_expired_pushed_commit_removes_directory_but_keeps_local_branch(
    tmp_path: Path,
) -> None:
    now = [0.0]
    root, manager = _repository(tmp_path, clock=lambda: now[0])
    remote = tmp_path / "remote.git"
    _git(tmp_path, "init", "--bare", "-q", str(remote))
    _git(root, "remote", "add", "origin", str(remote))
    lease = manager.acquire("task-bbbbcccc", manager.capture_baseline())
    (lease.path / "tracked.txt").write_text("pushed\n", encoding="utf-8")
    _git(lease.path, "add", "tracked.txt")
    _git(lease.path, "commit", "-qm", "pushed child")
    _git(lease.path, "push", "-u", "origin", "HEAD")

    handoff = manager.handoff(lease)
    assert handoff.retained is True
    assert handoff.all_commits_pushed is True
    now[0] = 24 * 60 * 60
    removed = WorktreeManager(root, clock=lambda: now[0]).cleanup_expired(())

    assert removed == (lease.task_id,)
    assert not lease.path.exists()
    assert lease.branch in _git(root, "branch", "--format=%(refname:short)").splitlines()


def test_candidate_parent_symlink_is_rejected_without_touching_external_tree(
    tmp_path: Path,
) -> None:
    root, manager = _repository(tmp_path)
    manager._ensure_managed_root()
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel"
    sentinel.write_text("safe", encoding="utf-8")
    (manager.managed_root / "nested").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="符号链接|边界"):
        manager.acquire(
            "task-ddddeeee", manager.capture_baseline(), name="nested/child"
        )

    assert sentinel.read_text(encoding="utf-8") == "safe"


def test_rule_parser_rejects_globs_traversal_duplicates_and_unknown_fields(
    tmp_path: Path,
) -> None:
    path = tmp_path / "worktree.yml"
    fixtures = (
        "version: 1\ncopy: ['*.env']\n",
        "version: 1\ncopy: ['../secret']\n",
        "version: 1\ncopy: [x, x]\n",
        "version: 1\nunknown: true\n",
        "version: 2\n",
    )
    for content in fixtures:
        path.write_text(content, encoding="utf-8")
        with pytest.raises(ValueError):
            read_rules(path)
