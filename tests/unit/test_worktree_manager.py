from __future__ import annotations

import subprocess
from pathlib import Path

from artcode.worktrees import WorktreeManager


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, check=True, text=True, stdout=subprocess.PIPE).stdout


def _repository(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "tests@example.com")
    _git(root, "config", "user.name", "Tests")
    (root / ".gitignore").write_text(".artcode/worktrees/\n", encoding="utf-8")
    (root / "shared.txt").write_text("base\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "initial")
    return root


def test_clean_worktree_is_removed_but_changed_one_is_preserved(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    manager = WorktreeManager(root)
    baseline = manager.capture_baseline()

    clean = manager.acquire("task-aaa11111", baseline)
    clean_handoff = manager.handoff(clean)
    assert clean_handoff.retained is False
    assert not clean.path.exists()

    changed = manager.acquire("task-bbb22222", baseline)
    (changed.path / "shared.txt").write_text("subagent change\n", encoding="utf-8")
    dirty_handoff = manager.handoff(changed)
    assert dirty_handoff.retained is True
    assert changed.path.exists()
    assert (root / "shared.txt").read_text(encoding="utf-8") == "base\n"
