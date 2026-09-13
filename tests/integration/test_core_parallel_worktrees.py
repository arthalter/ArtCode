from __future__ import annotations

import asyncio
from pathlib import Path
import subprocess
import platform
import sys

from artcode._subagent import LocalSubagents
from artcode._tool import LocalTools
from artcode._workspace import LocalWorkspace
from artcode.core.model import Completed, ModelMessage, ModelRequest, TextDelta, ToolRequest, ToolRequests
from artcode.core.subagent import ParentRunSnapshot, SubagentKind, TaskRequest, TaskState
from artcode.core.tool import PermissionMode, RunMode
from artcode.core.workspace import IsolationMode, ProcessRequest
from tests.contracts.test_subagent_interface import write_role


def git(root: Path, *args: str) -> None:
    subprocess.run(("git", *args), cwd=root, check=True, capture_output=True)


class WritingFactory:
    def __call__(self, model):
        class Writer:
            def __init__(self): self.calls = 0
            async def stream(self, request):
                self.calls += 1
                task = next(item.content for item in reversed(request.prompt) if item.role == "user")
                if self.calls == 1:
                    yield ToolRequests((ToolRequest("write", "write_file", f'{{"path":"same.txt","content":"{task}","overwrite":true}}'),))
                    yield Completed("tool_calls")
                else:
                    yield TextDelta(task)
                    yield Completed("stop")
            async def close(self): pass
        return Writer()


async def test_two_writers_use_frozen_baseline_and_isolated_worktrees(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "user.name", "Tests")
    git(root, "config", "user.email", "tests@example.invalid")
    (root / ".gitignore").write_text(".artcode/worktrees/\n", encoding="utf-8")
    (root / "same.txt").write_text("main", encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-qm", "initial")
    write_role(root / ".artcode/agents", "writer", allow=("write_file",), permission_mode="edit", isolation="worktree")
    workspace = LocalWorkspace(root)
    tools = LocalTools(permission_mode=PermissionMode.FULL)
    parent = ParentRunSnapshot(ModelRequest((ModelMessage("user", "parent"),)), tools.open_run(workspace, RunMode.CHAT))
    subagents = LocalSubagents(
        root / ".artcode/agents", tmp_path / "user", tmp_path / "builtin",
        workspace=workspace, tools=tools, model_factory=WritingFactory(), max_concurrency=2,
        background_tools=frozenset({"write_file"}),
    )
    subagents.refresh_roles()
    first = subagents.submit(TaskRequest(SubagentKind.DEFINITION, "first", role="writer", background=True), parent)
    second = subagents.submit(TaskRequest(SubagentKind.DEFINITION, "second", role="writer", background=True), parent)
    first_done, second_done = await asyncio.gather(subagents.wait(first.id), subagents.wait(second.id))

    assert first_done.state is second_done.state is TaskState.COMPLETED
    assert first_done.handoff.retained and second_done.handoff.retained
    assert first_done.handoff.path != second_done.handoff.path
    assert (first_done.handoff.path / "same.txt").read_text(encoding="utf-8") == "first"
    assert (second_done.handoff.path / "same.txt").read_text(encoding="utf-8") == "second"
    assert (root / "same.txt").read_text(encoding="utf-8") == "main"
    await subagents.close()


async def test_child_seatbelt_cannot_read_main_workspace(tmp_path: Path) -> None:
    if platform.system() != "Darwin" or not Path("/usr/bin/sandbox-exec").is_file():
        return
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "user.name", "Tests")
    git(root, "config", "user.email", "tests@example.invalid")
    (root / ".gitignore").write_text(".artcode/worktrees/\n", encoding="utf-8")
    (root / "secret.txt").write_text("main-secret", encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-qm", "initial")
    main = LocalWorkspace(root)
    lease = main.acquire_worktree("task-00000001", main.freeze_worktree())
    child = main.open_worktree(lease)

    own = await child.run_process(
        ProcessRequest(
            argv=(sys.executable, "-c", "from pathlib import Path; print(Path('secret.txt').read_text())"),
            isolation=IsolationMode.ENFORCED,
        )
    )
    escaped = await child.run_process(
        ProcessRequest(
            argv=(sys.executable, "-c", f"from pathlib import Path; print(Path({str(root / 'secret.txt')!r}).read_text())"),
            isolation=IsolationMode.ENFORCED,
        )
    )

    assert own.returncode == 0 and "main-secret" in own.stdout
    assert escaped.returncode != 0
    child.close()
    main.release_worktree(lease)
