from __future__ import annotations

from pathlib import Path
import subprocess

from artcode._workspace import LocalWorkspace


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(("git", *args), cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def test_two_worktree_scopes_modify_same_file_without_touching_main(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "user.name", "ArtCode Tests")
    git(root, "config", "user.email", "artcode@example.invalid")
    (root / ".gitignore").write_text(".artcode/worktrees/\n", encoding="utf-8")
    (root / "same.txt").write_text("main", encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-qm", "initial")
    main = LocalWorkspace(root)
    plan = main.freeze_worktree()
    first = main.acquire_worktree("task-00000001", plan)
    second = main.acquire_worktree("task-00000002", plan)
    first_scope = main.open_worktree(first)
    second_scope = main.open_worktree(second)

    first_scope.write_text(first_scope.prepare_target("same.txt", must_exist=True), "first", overwrite=True)
    second_scope.write_text(second_scope.prepare_target("same.txt", must_exist=True), "second", overwrite=True)

    assert (root / "same.txt").read_text(encoding="utf-8") == "main"
    assert (first.path / "same.txt").read_text(encoding="utf-8") == "first"
    assert (second.path / "same.txt").read_text(encoding="utf-8") == "second"
    assert first_scope.root != second_scope.root != main.root


def test_new_process_scope_recognizes_and_protects_retained_worktree(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "user.name", "Tests")
    git(root, "config", "user.email", "tests@example.invalid")
    (root / ".gitignore").write_text(".artcode/worktrees/\n", encoding="utf-8")
    (root / "base.txt").write_text("base", encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-qm", "initial")
    first = LocalWorkspace(root)
    lease = first.acquire_worktree("task-00000001", first.freeze_worktree())
    (lease.path / "result.txt").write_text("kept", encoding="utf-8")
    assert first.release_worktree(lease).retained
    first.close()

    restarted = LocalWorkspace(root)
    retained = restarted.list_managed_worktrees()

    assert len(retained) == 1
    assert retained[0].path == lease.path
    assert retained[0].untracked_changes == 1
    assert restarted.cleanup_worktrees(active_task_ids=set(), max_age_seconds=1) == ()
    assert (lease.path / "result.txt").read_text(encoding="utf-8") == "kept"
    restarted.close()
