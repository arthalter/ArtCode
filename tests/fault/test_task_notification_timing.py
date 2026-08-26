from __future__ import annotations

from pathlib import Path

from artcode.agent import NORMAL_AGENT_MODE, RequestPreparer
from artcode.background import BackgroundTaskDetail, BackgroundTaskStatus, TaskNotificationInbox
from artcode.bootstrap import _inject_task_notifications
from artcode.conversation import ConversationContext
from artcode.permissions import PermissionState
from artcode.prompting.assembler import PromptRequestAssembler
from artcode.subagents.models import AgentCreateRequest, AgentKind, SubagentResult, SubagentStopReason
from artcode.tools import ToolEnvironment, create_default_tool_registry
from artcode.worktrees import WorktreeHandoff


def _completed_detail(task_id: str) -> BackgroundTaskDetail:
    result = SubagentResult(task_id, SubagentStopReason.NATURAL, "final conclusion", 2)
    return BackgroundTaskDetail(
        task_id=task_id,
        kind="fork",
        role_name=None,
        status=BackgroundTaskStatus.COMPLETED,
        background=True,
        queued_at=1.0,
        started_at=2.0,
        finished_at=3.0,
        worktree_required=False,
        request=AgentCreateRequest(AgentKind.FORK, "task"),
        result=result,
        completion_index=1,
    )


async def test_notification_waits_for_next_request_edge(tmp_path: Path) -> None:
    """E14: a task completing while the parent request is already prepared
    never mutates that in-flight request; the notification lands only in the
    inbox and is consumed at the next safe request boundary."""
    registry = create_default_tool_registry()
    environment = ToolEnvironment.from_workspace(tmp_path)
    conversation = ConversationContext()
    preparer = RequestPreparer(
        conversation,
        PromptRequestAssembler(),
        registry,
        environment,
        PermissionState(),
    )
    inbox = TaskNotificationInbox()

    # The parent request is prepared (in flight) before the task finishes.
    first = await preparer.prepare(NORMAL_AGENT_MODE)
    first_text = "\n".join(str(m.get("content", "")) for m in first.request.messages)
    assert "<task-notification>" not in first_text

    # The task completes during the parent stream: only the inbox changes.
    inbox.add(_completed_detail("task-11111111"))
    assert len(inbox._pending) == 1
    unchanged = await preparer.prepare(NORMAL_AGENT_MODE)
    unchanged_text = "\n".join(str(m.get("content", "")) for m in unchanged.request.messages)
    assert "<task-notification>" not in unchanged_text

    # The next safe boundary (loop start) injects the notification.
    _inject_task_notifications(conversation, inbox)
    after = await preparer.prepare(NORMAL_AGENT_MODE)
    after_text = "\n".join(str(m.get("content", "")) for m in after.request.messages)
    assert "<task-notification>" in after_text
    assert "final conclusion" in after_text
    # Delivered once: a second drain is empty.
    assert inbox.drain() == ()
