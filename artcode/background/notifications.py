from __future__ import annotations

from collections import deque

from .models import BackgroundTaskDetail
from .presentation import render_handoff


MAX_NOTIFICATION_TEXT = 8_000


class TaskNotificationInbox:
    """Holds completion summaries until the parent reaches a safe request edge."""

    def __init__(self) -> None:
        self._pending: deque[BackgroundTaskDetail] = deque()
        self._delivered: set[str] = set()

    def add(self, detail: BackgroundTaskDetail) -> None:
        if detail.task_id not in self._delivered:
            self._pending.append(detail)

    def drain(self) -> tuple[str, ...]:
        messages: list[str] = []
        while self._pending:
            detail = self._pending.popleft()
            if detail.task_id in self._delivered:
                continue
            self._delivered.add(detail.task_id)
            messages.append(render_notification(detail))
        return tuple(messages)


def render_notification(detail: BackgroundTaskDetail) -> str:
    result = detail.result
    final_text = "" if result is None else result.final_text
    truncated = len(final_text) > MAX_NOTIFICATION_TEXT
    if truncated:
        final_text = final_text[:MAX_NOTIFICATION_TEXT]
    usage = {} if result is None else result.usage.to_dict()
    handoff = getattr(result, "handoff", None) if result is not None else None
    handoff_text = render_handoff(handoff)
    parts = [
        "<task-notification>",
        f"task_id: {detail.task_id}",
        f"status: {detail.status.value}",
        "result:",
        final_text or detail.error_message or "（任务未产生最终文本）",
    ]
    if truncated:
        parts.append("[结果已截断；完整内容请使用 task_get 查看。]")
    parts.extend((
        f"usage: {usage}",
        f"handoff: {handoff_text}",
        "</task-notification>",
    ))
    return "\n".join(parts)

