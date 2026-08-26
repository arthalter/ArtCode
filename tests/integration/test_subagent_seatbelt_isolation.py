from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from artcode.sandbox import SeatbeltSession
from artcode.worktrees import WorktreeManager


pytestmark = pytest.mark.skipif(
    not Path("/usr/bin/sandbox-exec").is_file(),
    reason="macOS sandbox-exec is required for the real Seatbelt integration",
)


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout.strip()


async def _sandboxed(session: SeatbeltSession, cwd: Path, *argv: str):
    process = await asyncio.create_subprocess_exec(
        *session.command_prefix(),
        *argv,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    return process.returncode, stdout.decode(), stderr.decode()


async def test_worktree_seatbelt_blocks_main_and_sibling_but_allows_shared_read_and_commit(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "tests@example.com")
    _git(root, "config", "user.name", "Tests")
    (root / ".gitignore").write_text(
        ".artcode/worktrees/\n.venv/\n", encoding="utf-8"
    )
    (root / "tracked.txt").write_text("main\n", encoding="utf-8")
    (root / ".venv").mkdir()
    (root / ".venv" / "dependency.txt").write_text("shared\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "initial")
    manager = WorktreeManager(root)
    baseline = manager.capture_baseline()
    lease = manager.acquire("task-1234abcd", baseline)
    sibling = manager.acquire("task-5678abcd", baseline)

    common_git = (root / ".git").resolve(strict=True)
    pointer = (lease.path / ".git").read_text(encoding="utf-8")
    linked_git = Path(pointer.removeprefix("gitdir: ").strip()).resolve(strict=True)
    branch_ref = common_git / "refs" / "heads" / lease.branch
    branch_log = common_git / "logs" / "refs" / "heads" / lease.branch
    shared = (root / ".venv").resolve()
    session = SeatbeltSession(
        lease.path,
        (),
        isolation_root=root,
        readable_paths=(shared, common_git),
        writable_paths=(
            common_git / "objects",
            linked_git,
            branch_ref,
            Path(f"{branch_ref}.lock"),
            branch_log,
            Path(f"{branch_log}.lock"),
            common_git / "packed-refs",
            common_git / "packed-refs.lock",
        ),
    )
    await session.start()
    try:
        main_read = await _sandboxed(session, lease.path, "/bin/cat", str(root / "tracked.txt"))
        sibling_read = await _sandboxed(
            session, lease.path, "/bin/cat", str(sibling.path / "tracked.txt")
        )
        shared_read = await _sandboxed(
            session, lease.path, "/bin/cat", str(shared / "dependency.txt")
        )
        shared_write = await _sandboxed(
            session,
            lease.path,
            "/bin/sh",
            "-c",
            f"printf bad > {shared / 'bad.txt'}",
        )
        (lease.path / "tracked.txt").write_text("child\n", encoding="utf-8")
        add = await _sandboxed(session, lease.path, "/usr/bin/git", "add", "tracked.txt")
        commit = await _sandboxed(
            session, lease.path, "/usr/bin/git", "commit", "-m", "child"
        )
    finally:
        session.close()

    assert main_read[0] != 0
    assert sibling_read[0] != 0
    assert shared_read[:2] == (0, "shared\n")
    assert shared_write[0] != 0
    assert not (shared / "bad.txt").exists()
    assert add[0] == 0
    assert commit[0] == 0
    assert (root / "tracked.txt").read_text(encoding="utf-8") == "main\n"
    handoff = manager.handoff(lease)
    assert handoff.retained is True and handoff.commits_ahead == 1
    assert manager.handoff(sibling).retained is False
