from __future__ import annotations

import subprocess
from pathlib import Path


def run_git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def init_repository(
    root: Path,
    *,
    files: dict[str, str] | None = None,
    ignore_worktrees: bool = True,
) -> None:
    """Create a real git repository at root with an initial commit."""
    run_git(root, "init", "-q")
    run_git(root, "config", "user.email", "tests@example.com")
    run_git(root, "config", "user.name", "ArtCode Tests")
    if ignore_worktrees:
        (root / ".gitignore").write_text(
            ".artcode/worktrees/" + chr(10), encoding="utf-8"
        )
    for relative, content in (files or {}).items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    run_git(root, "add", ".")
    run_git(root, "commit", "-qm", "initial commit")


def commit_all(root: Path, message: str = "commit") -> str:
    run_git(root, "add", ".")
    run_git(root, "commit", "-qm", message)
    return run_git(root, "rev-parse", "HEAD").strip()


def worktree_list(root: Path) -> list[str]:
    """Return the worktree paths registered in the repository."""
    porcelain = run_git(root, "worktree", "list", "--porcelain")
    paths: list[str] = []
    for line in porcelain.splitlines():
        if line.startswith("worktree "):
            paths.append(line[len("worktree "):])
    return paths


def branch_list(root: Path) -> set[str]:
    return {
        line.strip().lstrip("* ").strip()
        for line in run_git(root, "branch", "--format=%(refname:short)").splitlines()
        if line.strip()
    }
