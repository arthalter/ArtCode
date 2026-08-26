from __future__ import annotations

from pathlib import Path

from artcode.background import (
    BackgroundTaskDetail,
    BackgroundTaskStatus,
    TaskNotificationInbox,
)
from artcode.background.notifications import MAX_NOTIFICATION_TEXT, render_notification
from artcode.subagents.models import (
    AgentCreateRequest,
    AgentKind,
    SubagentResult,
    SubagentStopReason,
    UsageTotals,
)
from artcode.worktrees import WorktreeHandoff


def _detail(task_id: str, text: str, completion_index: int) -> BackgroundTaskDetail:
    handoff = WorktreeHandoff(
        baseline="a" * 40,
        branch="worktree-agent-deadbeef",
        path=Path("/tmp/worktree-agent-deadbeef"),
        retained=True,
        tracked_changes=1,
        staged_changes=2,
        untracked_changes=3,
        commits_ahead=4,
        has_upstream=True,
        all_commits_pushed=False,
        message="retained",
    )
    result = SubagentResult(
        task_id,
        SubagentStopReason.NATURAL,
        text,
        5,
        UsageTotals(10, 20, 30, 4, 6, 1),
        handoff=handoff,
        cache_prefix_preserved=True,
    )
    return BackgroundTaskDetail(
        task_id=task_id,
        kind="fork",
        role_name=None,
        status=BackgroundTaskStatus.COMPLETED,
        background=True,
        queued_at=1,
        started_at=2,
        finished_at=3,
        worktree_required=True,
        worktree_path=str(handoff.path),
        worktree_retained=True,
        request=AgentCreateRequest(AgentKind.FORK, "task"),
        result=result,
        completion_index=completion_index,
    )


def test_notification_contains_bounded_result_usage_and_full_handoff_summary() -> None:
    detail = _detail("task-deadbeef", "x" * (MAX_NOTIFICATION_TEXT + 1), 1)

    notification = render_notification(detail)

    assert notification.startswith("<task-notification>\n")
    assert notification.endswith("\n</task-notification>")
    assert "task_id: task-deadbeef" in notification
    assert "[结果已截断" in notification
    assert "x" * MAX_NOTIFICATION_TEXT in notification
    assert "x" * (MAX_NOTIFICATION_TEXT + 1) not in notification
    for field in (
        "baseline=",
        "branch=",
        "path=",
        "retained=",
        "tracked_changes=1",
        "staged_changes=2",
        "untracked_changes=3",
        "commits_ahead=4",
        "has_upstream=True",
        "all_commits_pushed=False",
    ):
        assert field in notification
    assert detail.result.final_text == "x" * (MAX_NOTIFICATION_TEXT + 1)


def test_notification_inbox_delivers_completion_order_once() -> None:
    inbox = TaskNotificationInbox()
    second = _detail("task-22222222", "second", 2)
    first = _detail("task-11111111", "first", 1)

    inbox.add(second)
    inbox.add(first)
    inbox.add(second)
    messages = inbox.drain()

    assert len(messages) == 2
    assert "task-22222222" in messages[0]
    assert "task-11111111" in messages[1]
    inbox.add(second)
    assert inbox.drain() == ()
