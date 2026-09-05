from __future__ import annotations

import asyncio
from pathlib import Path
import subprocess

from artcode._subagent import LocalSubagents
from artcode._tool import LocalTools
from artcode._workspace import LocalWorkspace
from artcode.core.model import Completed, ModelRequest, ProtocolFailure, TextDelta
from artcode.core.subagent import ParentRunSnapshot, SubagentKind, TaskRequest, TaskState
from artcode.core.tool import PermissionMode, RunMode
from tests.contracts.test_subagent_interface import write_role


class MixedFactory:
    def __call__(self, model: str | None):
        class Model:
            async def stream(self, request: ModelRequest):
                text = request.prompt[-1].content or ""
                if "fail" in text:
                    raise ProtocolFailure("injected")
                yield TextDelta("ok")
                yield Completed("stop")

            async def close(self):
                return None
        return Model()


async def test_one_provider_failure_does_not_break_sibling_task(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    write_role(root / ".artcode/agents", "reader")
    workspace = LocalWorkspace(root)
    tools = LocalTools(permission_mode=PermissionMode.FULL)
    parent = ParentRunSnapshot(
        __import__("artcode.core.model", fromlist=["ModelRequest", "ModelMessage"]).ModelRequest((__import__("artcode.core.model", fromlist=["ModelMessage"]).ModelMessage("user", "parent"),)),
        tools.open_run(workspace, RunMode.CHAT),
    )
    subagents = LocalSubagents(
        root / ".artcode/agents", tmp_path / "user", tmp_path / "builtin",
        workspace=workspace, tools=tools, model_factory=MixedFactory(), max_concurrency=2,
    )
    subagents.refresh_roles()
    failing = subagents.submit(TaskRequest(SubagentKind.DEFINITION, "fail", role="reader", background=True), parent)
    healthy = subagents.submit(TaskRequest(SubagentKind.DEFINITION, "healthy", role="reader", background=True), parent)

    failed, completed = await asyncio.gather(subagents.wait(failing.id), subagents.wait(healthy.id))
    assert failed.state is TaskState.FAILED
    assert completed.state is TaskState.COMPLETED
    await subagents.close()


async def test_queued_cancel_never_creates_model_or_worktree(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    write_role(root / ".artcode/agents", "reader")
    workspace = LocalWorkspace(root)
    tools = LocalTools()
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    def factory(model):
        class Blocking:
            async def stream(self, request):
                nonlocal calls
                calls += 1
                started.set()
                await release.wait()
                yield TextDelta("done")
                yield Completed("stop")
            async def close(self): pass
        return Blocking()

    parent = ParentRunSnapshot(ModelRequest((__import__("artcode.core.model", fromlist=["ModelMessage"]).ModelMessage("user", "p"),)), tools.open_run(workspace, RunMode.CHAT))
    subagents = LocalSubagents(
        root / ".artcode/agents", tmp_path / "user", tmp_path / "builtin",
        workspace=workspace, tools=tools, model_factory=factory, max_concurrency=1,
    )
    subagents.refresh_roles()
    first = subagents.submit(TaskRequest(SubagentKind.DEFINITION, "one", role="reader", background=True), parent)
    second = subagents.submit(TaskRequest(SubagentKind.DEFINITION, "two", role="reader", background=True), parent)
    await started.wait()
    cancelled = await subagents.cancel(second.id)
    release.set()
    await subagents.wait(first.id)

    assert cancelled.state is TaskState.CANCELLED
    assert calls == 1
    assert not (root / ".artcode/worktrees").exists()
    await subagents.close()


async def test_running_writer_cancel_preserves_completed_file_in_worktree(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    for args in (
        ("init", "-q"),
        ("config", "user.name", "Tests"),
        ("config", "user.email", "tests@example.invalid"),
    ):
        subprocess.run(("git", *args), cwd=root, check=True)
    (root / ".gitignore").write_text(".artcode/worktrees/\n", encoding="utf-8")
    (root / "base.txt").write_text("base", encoding="utf-8")
    subprocess.run(("git", "add", "."), cwd=root, check=True)
    subprocess.run(("git", "commit", "-qm", "initial"), cwd=root, check=True)
    write_role(root / ".artcode/agents", "writer", allow=("write_file",), permission_mode="edit", isolation="worktree")
    workspace = LocalWorkspace(root)
    tools = LocalTools(permission_mode=PermissionMode.FULL)
    second_round = asyncio.Event()

    def factory(_):
        class Writer:
            def __init__(self): self.calls = 0
            async def stream(self, request):
                from artcode.core.model import ToolRequest, ToolRequests
                self.calls += 1
                if self.calls == 1:
                    yield ToolRequests((ToolRequest("w", "write_file", '{"path":"result.txt","content":"kept"}'),))
                    yield Completed("tool_calls")
                else:
                    second_round.set()
                    await asyncio.Event().wait()
                    yield
            async def close(self): pass
        return Writer()

    parent = ParentRunSnapshot(ModelRequest((__import__("artcode.core.model", fromlist=["ModelMessage"]).ModelMessage("user", "p"),)), tools.open_run(workspace, RunMode.CHAT))
    subagents = LocalSubagents(
        root / ".artcode/agents", tmp_path / "user", tmp_path / "builtin",
        workspace=workspace, tools=tools, model_factory=factory,
        background_tools=frozenset({"write_file"}),
    )
    subagents.refresh_roles()
    task = subagents.submit(TaskRequest(SubagentKind.DEFINITION, "write", role="writer", background=True), parent)
    await second_round.wait()
    cancelled = await subagents.cancel(task.id)

    assert cancelled.state is TaskState.CANCELLED
    assert cancelled.handoff is not None and cancelled.handoff.retained
    assert (cancelled.handoff.path / "result.txt").read_text(encoding="utf-8") == "kept"
    await subagents.close()
