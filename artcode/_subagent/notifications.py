from __future__ import annotations

from artcode.core.subagent import TaskNotification

from .tasks import TaskRecord


MAX_RESULT_CHARS = 8_000


def notification(record: TaskRecord) -> TaskNotification:
    truncated = len(record.result) > MAX_RESULT_CHARS
    return TaskNotification(
        record.id,
        record.state,
        record.result[:MAX_RESULT_CHARS],
        record.usage,
        record.handoff,
        truncated,
    )
