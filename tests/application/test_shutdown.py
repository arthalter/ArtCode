from __future__ import annotations

from pathlib import Path

from artcode._application import LocalApplication
from artcode.core.application import ExitRequested
from artcode.core.application import StateOutput
from artcode.core.model import Usage
from artcode.core.subagent import SubagentKind, TaskSnapshot, TaskState
from tests.application.conftest import FakeModel, options


async def test_exit_closes_owned_resources_idempotently(tmp_path: Path) -> None:
    model = FakeModel()
    app = await LocalApplication.create(options(tmp_path), model=model)

    result = await app.handle("/exit")
    await app.close()

    assert result == (ExitRequested(),)
    assert model.closed == 1
    assert app.workspace.active_process_count == 0


async def test_active_task_exit_supports_wait_cancel_and_return_branches(tmp_path: Path) -> None:
    class Tasks:
        def __init__(self):
            self.task = TaskSnapshot(
                "task-00000001", SubagentKind.DEFINITION, "work", "reader",
                TaskState.RUNNING, True, 0.0,
            )
            self.waited = self.cancelled = self.closed = 0
        def list(self): return (self.task,)
        async def wait(self, task_id):
            self.waited += 1
            self.task = __import__("dataclasses").replace(self.task, state=TaskState.COMPLETED)
            return self.task
        async def cancel(self, task_id):
            self.cancelled += 1
            self.task = __import__("dataclasses").replace(self.task, state=TaskState.CANCELLED)
            return self.task
        async def close(self): self.closed += 1
        def take_notifications(self): return ()

    class Choice:
        def __init__(self, value): self.value = value
        async def choose_active_task_exit(self, tasks): return self.value

    for choice in ("return", "wait", "cancel"):
        case_root = tmp_path / choice
        case_root.mkdir()
        app = await LocalApplication.create(options(case_root), model=FakeModel())
        tasks = Tasks()
        app.subagents = tasks
        app.interaction = Choice(choice)

        result = await app.handle("/exit")

        if choice == "return":
            assert isinstance(result[0], StateOutput)
            assert app.snapshot().closed is False
            await app.close()
        else:
            assert result == (ExitRequested(),)
            assert tasks.waited == (choice == "wait")
            assert tasks.cancelled == (choice == "cancel")
