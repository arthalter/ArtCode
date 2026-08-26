from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from artcode.background import BackgroundTaskManager
from artcode.worktrees import WorktreeManager
from tests.fixtures.git_repositories import branch_list, init_repository, run_git


async def test_abnormal_exit_does_not_recover_tasks_and_worktree_is_recognized(
    tmp_path: Path,
) -> None:
    """E16: an abnormal exit (simulated by dropping the manager without
    handoff) never resurrects background tasks; the next run recognizes the
    leftover worktree through ownership metadata and keeps protecting it."""
    init_repository(tmp_path, files={"main.txt": "original" + chr(10)})
    # "Process A" crashes right after acquiring a worktree and writing.
    manager_a = WorktreeManager(tmp_path)
    baseline = manager_a.capture_baseline()
    lease = manager_a.acquire("task-aaaaaaaa", baseline)
    (lease.path / "result.txt").write_text("survives", encoding="utf-8")
    del manager_a  # no handoff, no close: the process is gone

    # "Process B" starts: a fresh task manager has no tasks at all.
    tasks_b = BackgroundTaskManager()
    assert tasks_b.list() == ()

    # The startup scan recognizes the leftover worktree and protects it.
    manager_b = WorktreeManager(tmp_path)
    removed = manager_b.cleanup_expired([], max_age_seconds=24 * 3600)
    assert removed == ()
    assert lease.path.exists()
    found = manager_b.find("task-aaaaaaaa")
    assert found is not None
    assert found.path == lease.path
    assert (lease.path / "result.txt").read_text(encoding="utf-8") == "survives"


async def test_task_details_never_persist_across_processes(tmp_path: Path) -> None:
    """E17: task details live only inside the current process; after a
    simulated exit nothing task-shaped is written anywhere under the
    workspace except the intended worktree metadata."""
    init_repository(tmp_path, files={"main.txt": "original" + chr(10)})
    manager = WorktreeManager(tmp_path)
    baseline = manager.capture_baseline()
    lease = manager.acquire("task-cccccccc", baseline)
    manager.handoff(lease)  # clean, auto removed
    tasks = BackgroundTaskManager()
    from artcode.subagents.models import AgentCreateRequest, AgentKind, SubagentResult, SubagentStopReason

    async def runner(task_id: str):
        return SubagentResult(task_id, SubagentStopReason.NATURAL, "done", 1)

    summary = tasks.submit(
        AgentCreateRequest(AgentKind.FORK, "task", None, True), runner, worktree_required=False
    )
    await tasks.wait(summary.task_id)
    assert tasks.get(summary.task_id) is not None

    # Simulate exit: drop both managers.
    del tasks, manager

    # Nothing task-shaped was persisted anywhere in the workspace: the
    # worktree was clean (auto removed) so no ownership metadata remains.
    metadata_root = tmp_path / ".artcode" / "worktrees" / ".metadata"
    metadata_files = list(metadata_root.glob("*.json")) if metadata_root.exists() else []
    assert metadata_files == []
    # No session journal or task database contains the fork task id.
    for path in tmp_path.rglob("*"):
        assert "task-" not in path.name


def test_two_process_restart_scenario(tmp_path: Path) -> None:
    """H10: a real subprocess creates and finishes worktrees; after the
    process exits, a fresh process sees the clean one gone and the one with
    an unpushed commit retained with files and commit intact."""
    init_repository(tmp_path, files={"main.txt": "original" + chr(10)})
    script = "\n".join([
        "import sys",
        "from pathlib import Path",
        "from artcode.worktrees import WorktreeManager",
        "import subprocess",
        "repo = Path(sys.argv[1])",
        "m = WorktreeManager(repo)",
        "baseline = m.capture_baseline()",
        "clean = m.acquire('task-aaaaaaaa', baseline)",
        "m.handoff(clean)",
        "kept = m.acquire('task-bbbbbbbb', baseline)",
        "(kept.path / 'result.txt').write_text('precious', encoding='utf-8')",
        "subprocess.run(['git', 'add', '.'], cwd=kept.path, check=True)",
        "subprocess.run(['git', 'commit', '-qm', 'kept work'], cwd=kept.path, check=True)",
        "m.handoff(kept)",
        "print(kept.path)",
    ])
    completed = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    kept_path = Path(completed.stdout.strip())
    # The clean worktree was removed inside the first process.
    assert not (tmp_path / ".artcode" / "worktrees" / "agent-aaaaaaaa").exists()
    assert kept_path.exists()

    # "Restart": a new process scans and must keep the committed worktree.
    manager = WorktreeManager(tmp_path)
    removed = manager.cleanup_expired([], max_age_seconds=24 * 3600)
    assert removed == ()
    found = manager.find("task-bbbbbbbb")
    assert found is not None and found.path == kept_path
    assert (kept_path / "result.txt").read_text(encoding="utf-8") == "precious"
    head = run_git(kept_path, "rev-parse", "HEAD").strip()
    assert len(head) == 40
    assert "worktree-agent-bbbbbbbb" in branch_list(tmp_path)
