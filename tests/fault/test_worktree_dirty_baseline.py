from __future__ import annotations

from pathlib import Path

import pytest

from artcode.worktrees import WorktreeManager
from tests.fixtures.git_repositories import commit_all, init_repository, run_git


@pytest.mark.parametrize(
    "dirty_kind",
    ["tracked", "untracked", "staged"],
    ids=("tracked-modified", "untracked-new", "staged-changes"),
)
def test_dirty_main_workspace_is_not_copied_into_new_worktree(
    tmp_path: Path, dirty_kind: str
) -> None:
    """F07: worktrees are created from the recorded HEAD no matter which
    kind of dirt the main workspace carries; the dirt is never copied and
    the main workspace keeps its state."""
    init_repository(tmp_path, files={"main.txt": "original" + chr(10)})
    main_file = tmp_path / "main.txt"
    if dirty_kind in {"tracked", "staged"}:
        main_file.write_text("modified in main" + chr(10), encoding="utf-8")
        if dirty_kind == "staged":
            run_git(tmp_path, "add", "main.txt")
    if dirty_kind == "untracked":
        (tmp_path / "new.txt").write_text("brand new" + chr(10), encoding="utf-8")

    manager = WorktreeManager(tmp_path)
    baseline = manager.capture_baseline()
    lease = manager.acquire("task-12345678", baseline)

    # The worktree starts from the committed baseline only.
    assert (lease.path / "main.txt").read_text(encoding="utf-8") == "original" + chr(10)
    assert not (lease.path / "new.txt").exists()

    # The main workspace keeps its dirty state untouched.
    if dirty_kind in {"tracked", "staged"}:
        assert main_file.read_text(encoding="utf-8") == "modified in main" + chr(10)
    if dirty_kind == "untracked":
        assert (tmp_path / "new.txt").read_text(encoding="utf-8") == "brand new" + chr(10)

    # A clean worktree with no changes is auto-removed at handoff; the
    # handoff message states the baseline did not include main dirt.
    handoff = manager.handoff(lease)
    assert handoff.retained is False
    assert "不包含主工作区未提交修改" in handoff.message

    # Committing new main-workspace content after baseline capture still
    # leaves the worktree on the recorded baseline (N5 determinism).
    main_file.write_text("committed later" + chr(10), encoding="utf-8")
    commit_all(tmp_path, "later commit")
    later = manager.acquire("task-87654321", baseline)
    assert (later.path / "main.txt").read_text(encoding="utf-8") == "original" + chr(10)
    manager.handoff(later)
