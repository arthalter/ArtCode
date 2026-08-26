from __future__ import annotations

import asyncio

from prompt_toolkit import PromptSession
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from artcode.background import BackgroundTaskManager, BackgroundTaskStatus
from artcode.runtime import ArtCodeRuntime
from artcode.subagents.models import (
    AgentCreateRequest,
    AgentKind,
    SubagentResult,
    SubagentStopReason,
)
from artcode.tui import PromptToolkitTui


async def test_prompt_toolkit_ctrl_b_promotes_without_triggering_ctrl_c() -> None:
    with create_pipe_input() as pipe:
        tui = PromptToolkitTui(renderer=object())  # type: ignore[arg-type]
        tui._session = PromptSession(
            input=pipe,
            output=DummyOutput(),
            multiline=True,
        )
        background = asyncio.Event()
        cancelled = asyncio.Event()
        tui.begin_generation_controls(cancelled.set, background.set)
        await asyncio.sleep(0)

        pipe.send_bytes(b"\x02")
        await asyncio.wait_for(background.wait(), timeout=1)

        assert cancelled.is_set() is False
        pipe.send_bytes(b"\x03")
        await asyncio.wait_for(cancelled.wait(), timeout=1)
        await tui.end_generation_controls()


class _ExitTui:
    def __init__(self, choice: str, gate: asyncio.Event | None = None) -> None:
        self.choice = choice
        self.gate = gate
        self.messages: list[str] = []

    async def choose_active_task_exit(self, _summaries) -> str:
        if self.gate is not None:
            self.gate.set()
        return self.choice

    def show_help(self, message: str) -> None:
        self.messages.append(message)


async def _active_runtime(choice: str):
    gate = asyncio.Event()
    manager = BackgroundTaskManager(id_factory=lambda: "1234abcd")

    async def runner(task_id: str) -> SubagentResult:
        await gate.wait()
        return SubagentResult(task_id, SubagentStopReason.NATURAL, "done", 1)

    manager.submit(
        AgentCreateRequest(AgentKind.DEFINITION, "task", "reader", True),
        runner,
        worktree_required=False,
    )
    await asyncio.sleep(0)
    runtime = object.__new__(ArtCodeRuntime)
    runtime.task_manager = manager
    runtime.tui = _ExitTui(choice, gate if choice == "wait" else None)
    return runtime, manager, gate


async def test_runtime_exit_can_return_without_abandoning_active_task() -> None:
    runtime, manager, gate = await _active_runtime("return")

    assert await runtime._confirm_exit_with_active_tasks() is False
    assert manager.active()

    gate.set()
    await manager.wait_all()


async def test_runtime_exit_can_wait_for_all_tasks() -> None:
    runtime, manager, _gate = await _active_runtime("wait")

    assert await runtime._confirm_exit_with_active_tasks() is True
    assert manager.active() == ()
    assert manager.list()[0].status is BackgroundTaskStatus.COMPLETED


async def test_runtime_exit_can_cancel_then_finish_worktree_protection_path() -> None:
    runtime, manager, _gate = await _active_runtime("cancel")

    assert await runtime._confirm_exit_with_active_tasks() is True
    assert manager.active() == ()
    assert manager.list()[0].status is BackgroundTaskStatus.CANCELLED
