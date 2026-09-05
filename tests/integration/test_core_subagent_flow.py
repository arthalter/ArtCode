from __future__ import annotations

import asyncio
from pathlib import Path

from artcode._subagent import LocalSubagents
from artcode._tool import LocalTools
from artcode._workspace import LocalWorkspace
from artcode.core.model import Completed, ModelMessage, ModelRequest, TextDelta
from artcode.core.subagent import ParentRunSnapshot, SubagentKind, TaskRequest, TaskState
from artcode.core.tool import PermissionMode, RunMode
from tests.contracts.test_subagent_interface import write_role


class GateFactory:
    def __init__(self) -> None:
        self.gates: dict[str, asyncio.Event] = {}

    def __call__(self, model):
        gates = self.gates
        class Model:
            async def stream(self, request):
                task = request.prompt[-1].content
                gate = gates.setdefault(task, asyncio.Event())
                await gate.wait()
                yield TextDelta(task)
                yield Completed("stop")
            async def close(self): pass
        return Model()


async def test_completion_notifications_follow_completion_not_enqueue_order(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    write_role(root / ".artcode/agents", "reader")
    workspace = LocalWorkspace(root)
    tools = LocalTools(permission_mode=PermissionMode.FULL)
    factory = GateFactory()
    parent = ParentRunSnapshot(ModelRequest((ModelMessage("user", "parent"),)), tools.open_run(workspace, RunMode.CHAT))
    subagents = LocalSubagents(
        root / ".artcode/agents", tmp_path / "user", tmp_path / "builtin",
        workspace=workspace, tools=tools, model_factory=factory, max_concurrency=4,
    )
    subagents.refresh_roles()
    tasks = [
        subagents.submit(TaskRequest(SubagentKind.DEFINITION, name, role="reader", background=True), parent)
        for name in ("one", "two", "three")
    ]
    while len(factory.gates) < 3:
        await asyncio.sleep(0)
    for name in ("three", "one", "two"):
        factory.gates[name].set()
        await subagents.wait(next(item.id for item in tasks if subagents.get(item.id).task == name))

    assert [item.result for item in subagents.take_notifications()] == ["three", "one", "two"]
    await subagents.close()


async def test_foreground_timeout_and_manual_background_keep_same_task_state(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    write_role(root / ".artcode/agents", "reader")
    workspace = LocalWorkspace(root)
    tools = LocalTools()
    factory = GateFactory()
    parent = ParentRunSnapshot(ModelRequest((ModelMessage("user", "parent"),)), tools.open_run(workspace, RunMode.CHAT))
    subagents = LocalSubagents(
        root / ".artcode/agents", tmp_path / "user", tmp_path / "builtin",
        workspace=workspace, tools=tools, model_factory=factory,
        foreground_timeout_seconds=0.01,
    )
    subagents.refresh_roles()
    task = subagents.submit(TaskRequest(SubagentKind.DEFINITION, "slow", role="reader"), parent)

    background = await subagents.wait_foreground(task.id)
    same = subagents.background(task.id)
    factory.gates["slow"].set()
    done = await subagents.wait(task.id)

    assert background.id == same.id == done.id == task.id
    assert background.background is same.background is done.background is True
    assert done.result == "slow"
    assert len(subagents.take_notifications()) == 1
    await subagents.close()


async def test_manual_background_event_immediately_releases_foreground_wait(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    write_role(root / ".artcode/agents", "reader")
    workspace = LocalWorkspace(root)
    tools = LocalTools()
    factory = GateFactory()
    parent = ParentRunSnapshot(ModelRequest((ModelMessage("user", "parent"),)), tools.open_run(workspace, RunMode.CHAT))
    subagents = LocalSubagents(
        root / ".artcode/agents", tmp_path / "user", tmp_path / "builtin",
        workspace=workspace, tools=tools, model_factory=factory,
        foreground_timeout_seconds=30,
    )
    subagents.refresh_roles()
    task = subagents.submit(TaskRequest(SubagentKind.DEFINITION, "manual", role="reader"), parent)
    foreground_wait = asyncio.create_task(subagents.wait_foreground(task.id))
    while "manual" not in factory.gates:
        await asyncio.sleep(0)

    subagents.background(task.id)
    background = await asyncio.wait_for(foreground_wait, 0.5)
    assert background.background is True and background.state is TaskState.RUNNING
    factory.gates["manual"].set()
    assert (await subagents.wait(task.id)).result == "manual"
    await subagents.close()
