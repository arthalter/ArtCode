from __future__ import annotations

import asyncio
from dataclasses import replace
import json
from pathlib import Path

import pytest

from artcode._subagent import LocalSubagents
from artcode._tool import LocalTools
from artcode._workspace import LocalWorkspace
from artcode.core.model import Completed, ModelMessage, ModelRequest, TextDelta
from artcode.core.subagent import TaskState
from artcode.core.tool import RunMode, ToolCall
from tests.contracts.test_subagent_interface import write_role


class HeldModel:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def stream(self, request):
        self.started.set()
        await self.release.wait()
        yield TextDelta("child finished")
        yield Completed("stop")

    async def close(self):
        pass


async def test_foreground_deadline_returns_background_task_id_through_tool(tmp_path: Path) -> None:
    workspace = LocalWorkspace(tmp_path)
    tools = LocalTools(tool_timeout_seconds=0.04)
    model = HeldModel()
    write_role(tmp_path / ".artcode/agents", "reader")
    subagents = LocalSubagents(
        tmp_path / ".artcode/agents", tmp_path / "user", tmp_path / "builtin",
        workspace=workspace, tools=tools, model_factory=lambda _: model,
        foreground_timeout_seconds=0.04,
    )
    subagents.refresh_roles()
    tools.register_subagents(subagents)
    run = replace(
        tools.open_run(workspace, RunMode.CHAT),
        execution_data=ModelRequest((ModelMessage("user", "parent"),)),
    )
    try:
        result, = await asyncio.wait_for(
            tools.execute_batch(run, (ToolCall("delegate", "agent", json.dumps({
                "type": "definition", "task": "slow child", "role": "reader",
            })),)),
            timeout=1,
        )
        assert result.ok is True, result
        task_id = json.loads(result.content)["task_id"]
        assert len(subagents.list()) == 1
        assert subagents.get(task_id).background is True
        assert subagents.get(task_id).state is TaskState.RUNNING
        model.release.set()
        assert (await subagents.wait(task_id)).result == "child finished"
        assert [notice.task_id for notice in subagents.take_notifications()] == [task_id]
    finally:
        model.release.set()
        await subagents.close()
        await tools.close()
        await workspace.aclose()


async def test_user_cancellation_still_interrupts_foreground_tool_wait(tmp_path: Path) -> None:
    workspace = LocalWorkspace(tmp_path)
    tools = LocalTools()
    model = HeldModel()
    write_role(tmp_path / ".artcode/agents", "reader")
    subagents = LocalSubagents(
        tmp_path / ".artcode/agents", tmp_path / "user", tmp_path / "builtin",
        workspace=workspace, tools=tools, model_factory=lambda _: model,
        foreground_timeout_seconds=10,
    )
    subagents.refresh_roles()
    tools.register_subagents(subagents)
    run = replace(
        tools.open_run(workspace, RunMode.CHAT),
        execution_data=ModelRequest((ModelMessage("user", "parent"),)),
    )
    execution = asyncio.create_task(tools.execute_batch(run, (ToolCall(
        "delegate", "agent", json.dumps({"type": "definition", "task": "child", "role": "reader"}),
    ),)))
    try:
        await asyncio.wait_for(model.started.wait(), 1)
        execution.cancel()
        with pytest.raises(asyncio.CancelledError):
            await execution
        task, = subagents.list()
        assert task.background is True and task.state is TaskState.RUNNING
    finally:
        execution.cancel()
        await asyncio.gather(execution, return_exceptions=True)
        model.release.set()
        await subagents.close()
        await tools.close()
        await workspace.aclose()
