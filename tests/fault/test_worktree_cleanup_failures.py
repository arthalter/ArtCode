from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from artcode.worktrees.manager import WorktreeManager
from tests.fixtures.git_repositories import init_repository, worktree_list, branch_list


def _manager_with_retained_worktree(
    tmp_path: Path,
) -> tuple[WorktreeManager, str, Path, str]:
    """Create a manager plus one retained (dirty) system worktree."""
    init_repository(tmp_path)
    manager = WorktreeManager(tmp_path)
    baseline = manager.capture_baseline()
    lease = manager.acquire("task-11111111", baseline)
    (lease.path / "dirty.txt").write_text("keep me", encoding="utf-8")
    manager.handoff(lease)  # retained because of the untracked file
    assert lease.path.exists()
    return manager, lease.task_id, lease.path, lease.branch


async def test_corrupt_metadata_is_never_deleted(tmp_path: Path) -> None:
    manager, task_id, path, _ = _manager_with_retained_worktree(tmp_path)
    metadata = manager.metadata_root / f"{task_id}.json"
    metadata.write_text("{not json", encoding="utf-8")

    removed = manager.cleanup_expired([], max_age_seconds=0)

    assert removed == ()
    assert path.exists()
    assert "损坏" in " ".join(manager.last_cleanup_diagnostics)


async def test_metadata_race_after_metadata_removal_preserves_directory(
    tmp_path: Path,
) -> None:
    manager, task_id, path, _ = _manager_with_retained_worktree(tmp_path)
    metadata = manager.metadata_root / f"{task_id}.json"
    metadata.unlink()

    removed = manager.cleanup_expired([], max_age_seconds=0)

    assert removed == ()
    assert path.exists()
    # Without metadata the managed directory is untouched by the scanner.


async def test_git_status_failure_preserves_worktree(tmp_path: Path) -> None:
    manager, task_id, path, _ = _manager_with_retained_worktree(tmp_path)
    manager.handoff.__self__  # noqa: B018  (access only, keeps import honest)

    def failing_git(*args: str, cwd: Path) -> str:
        if args[0] == "status":
            raise RuntimeError("simulated git failure")
        return manager._git(*args, cwd=cwd)

    with patch.object(manager, "_git", side_effect=failing_git):
        removed = manager.cleanup_expired([], max_age_seconds=0)

    assert removed == ()
    assert path.exists()
    assert any("保留" in message for message in manager.last_cleanup_diagnostics)


async def test_active_task_worktree_is_never_cleaned(tmp_path: Path) -> None:
    manager, task_id, path, _ = _manager_with_retained_worktree(tmp_path)
    # Re-register the task as active while keeping the retained directory.
    manager._active_task_ids.add(task_id)

    removed = manager.cleanup_expired([task_id], max_age_seconds=0)

    assert removed == ()
    assert path.exists()
    assert any("活动" in message for message in manager.last_cleanup_diagnostics)


async def test_clean_expired_worktree_deletes_only_owned_targets(
    tmp_path: Path,
) -> None:
    init_repository(tmp_path)
    manager = WorktreeManager(tmp_path)
    baseline = manager.capture_baseline()
    clean_lease = manager.acquire("task-aaaaaaaa", baseline)
    manager.handoff(clean_lease)  # clean -> auto removed
    assert not clean_lease.path.exists()

    dirty_lease = manager.acquire("task-bbbbbbbb", baseline)
    (dirty_lease.path / "dirty.txt").write_text("keep", encoding="utf-8")
    manager.handoff(dirty_lease)
    sentinel = dirty_lease.path / "dirty.txt"

    removed = manager.cleanup_expired([], max_age_seconds=0)

    assert removed == ()
    assert sentinel.read_text(encoding="utf-8") == "keep"
    assert dirty_lease.path.exists()


async def test_manual_worktree_without_metadata_is_never_cleaned(
    tmp_path: Path,
) -> None:
    init_repository(tmp_path)
    manager = WorktreeManager(tmp_path)
    manual = tmp_path / ".artcode" / "worktrees" / "manual-keep"
    manual.mkdir(parents=True)
    # A real user-created worktree with no ownership metadata:
    import subprocess
    subprocess.run(
        ["git", "worktree", "add", "-b", "worktree-manual-keep", str(manual)],
        cwd=tmp_path,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    removed = manager.cleanup_expired([], max_age_seconds=0)

    assert removed == ()
    assert manual.exists()


async def test_discard_rejects_active_task(tmp_path: Path) -> None:
    manager, task_id, path, _ = _manager_with_retained_worktree(tmp_path)
    manager._active_task_ids.add(task_id)

    with pytest.raises(ValueError, match="仍在运行"):
        manager.discard(task_id)
    assert path.exists()


async def test_discard_unknown_task_id_is_rejected(tmp_path: Path) -> None:
    init_repository(tmp_path)
    manager = WorktreeManager(tmp_path)
    with pytest.raises(ValueError, match="任务 ID"):
        manager.discard("task-zzzzzzzz")
    with pytest.raises(KeyError):
        manager.discard("task-12345678")


async def test_discard_after_confirmation_removes_only_target(
    tmp_path: Path,
) -> None:
    manager, task_id, path, branch = _manager_with_retained_worktree(tmp_path)
    # A second retained worktree acts as a sentinel.
    baseline = manager.capture_baseline()
    other = manager.acquire("task-22222222", baseline)
    (other.path / "other.txt").write_text("other", encoding="utf-8")
    manager.handoff(other)
    assert other.path.exists()

    manager.discard(task_id)

    assert not path.exists()
    assert branch not in branch_list(tmp_path)
    assert not (manager.metadata_root / f"{task_id}.json").exists()
    assert other.path.exists()
    assert (other.path / "other.txt").read_text(encoding="utf-8") == "other"
    # The remaining retained worktree is still listed by git.
    assert str(other.path) in worktree_list(tmp_path)


async def test_discard_metadata_forgery_is_rejected(tmp_path: Path) -> None:
    init_repository(tmp_path)
    manager = WorktreeManager(tmp_path)
    baseline = manager.capture_baseline()
    lease = manager.acquire("task-33333333", baseline)
    (lease.path / "dirty.txt").write_text("keep", encoding="utf-8")
    manager.handoff(lease)
    metadata = manager.metadata_root / f"{lease.task_id}.json"
    forged = json.loads(metadata.read_text(encoding="utf-8"))
    forged["branch"] = "worktree-agent-deadbeef"
    metadata.write_text(json.dumps(forged), encoding="utf-8")

    with pytest.raises(KeyError):
        manager.discard(lease.task_id)
    assert lease.path.exists()
