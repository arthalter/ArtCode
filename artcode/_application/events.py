from __future__ import annotations

from artcode.core.agent import RunError, RunFinished, TextEvent, ToolBatchEvent, UsageEvent
from artcode.core.application import ErrorOutput, RunStopped, StateOutput, TextOutput


def application_event(event):
    if isinstance(event, TextEvent):
        return TextOutput(event.text, streaming=True)
    if isinstance(event, UsageEvent):
        return StateOutput("usage", event.usage)
    if isinstance(event, ToolBatchEvent):
        return StateOutput("tool_batch", event)
    if isinstance(event, RunError):
        return ErrorOutput(f"{event.category}: {event.message}")
    if isinstance(event, RunFinished):
        return RunStopped(event.outcome.stop_reason.value, event.outcome.rounds)
    return None
