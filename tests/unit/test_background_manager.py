from __future__ import annotations

import asyncio

from artcode.background import BackgroundTaskManager, BackgroundTaskStatus
from artcode.subagents.models import AgentCreateRequest, AgentKind, SubagentResult, SubagentStopReason


async def test_background_manager_queues_fifth_task_and_reports_completion_order() -> None:
    gates = [asyncio.Event() for _ in range(5)]
    started: list[int] = []

    async def run(index: int, task_id: str) -> SubagentResult:
        started.append(index)
        await gates[index].wait()
        return SubagentResult(task_id, SubagentStopReason.NATURAL, f"done-{index}", 1)

    manager = BackgroundTaskManager()
    summaries = [
        manager.submit(
            AgentCreateRequest(AgentKind.DEFINITION, f"task {index}", "role", True),
            lambda task_id, index=index: run(index, task_id),
            worktree_required=False,
        )
        for index in range(5)
    ]
    await asyncio.sleep(0)
    assert len(started) == 4
    assert manager.get(summaries[-1].task_id).status is BackgroundTaskStatus.QUEUED

    gates[2].set()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert 4 in started
    for gate in gates:
        gate.set()
    await asyncio.gather(*(manager.wait(item.task_id) for item in summaries))
    details = [manager.get(item.task_id) for item in summaries]
    assert all(item is not None and item.status is BackgroundTaskStatus.COMPLETED for item in details)
    assert details[2].completion_index < details[0].completion_index


async def test_notifications_only_follow_background_completion_and_are_deduplicated() -> None:
    notifications = []
    suffixes = iter(("11111111", "22222222", "33333333"))
    manager = BackgroundTaskManager(
        on_completed=notifications.append,
        id_factory=lambda: next(suffixes),
    )

    async def completed(task_id: str) -> SubagentResult:
        return SubagentResult(task_id, SubagentStopReason.NATURAL, "done", 1)

    foreground = manager.submit(
        AgentCreateRequest(AgentKind.DEFINITION, "front", "role", False),
        completed,
        worktree_required=False,
    )
    background = manager.submit(
        AgentCreateRequest(AgentKind.DEFINITION, "back", "role", True),
        completed,
        worktree_required=False,
    )
    await manager.wait_all()

    assert [item.task_id for item in notifications] == [background.task_id]
    assert manager.get(foreground.task_id).completion_index is not None
    assert manager.cancel(background.task_id) is False
    assert [item.task_id for item in notifications] == [background.task_id]


async def test_promoted_foreground_task_notifies_once_on_later_completion() -> None:
    notifications = []
    gate = asyncio.Event()
    manager = BackgroundTaskManager(
        on_completed=notifications.append,
        id_factory=lambda: "abcdef12",
    )

    async def runner(task_id: str) -> SubagentResult:
        await gate.wait()
        return SubagentResult(task_id, SubagentStopReason.NATURAL, "done", 1)

    summary = manager.submit(
        AgentCreateRequest(AgentKind.DEFINITION, "front", "role", False),
        runner,
        worktree_required=False,
    )
    await asyncio.sleep(0)
    assert manager.promote_to_background(summary.task_id) is True
    gate.set()
    await manager.wait_all()

    assert [item.task_id for item in notifications] == [summary.task_id]
