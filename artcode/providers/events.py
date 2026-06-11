from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from .tool_calls import ToolCall

CONTENT_DELTA = "content_delta"
TOOL_CALLS = "tool_calls"
TOKEN_USAGE = "token_usage"
DONE = "done"
VALID_EVENT_TYPES = {CONTENT_DELTA, TOOL_CALLS, TOKEN_USAGE, DONE}


def content_delta_event(text: str) -> dict[str, Any]:
    event = {"type": CONTENT_DELTA, "text": text}
    validate_event(event)
    return event


def tool_calls_event(tool_calls: Sequence[ToolCall]) -> dict[str, Any]:
    event = {"type": TOOL_CALLS, "tool_calls": list(tool_calls)}
    validate_event(event)
    return event


def token_usage_event(
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    total_tokens: int | None = None,
) -> dict[str, Any]:
    event = {
        "type": TOKEN_USAGE,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }
    validate_event(event)
    return event


def done_event() -> dict[str, Any]:
    event = {"type": DONE}
    validate_event(event)
    return event


def validate_event(event: dict[str, Any]) -> None:
    event_type = event.get("type")
    if event_type not in VALID_EVENT_TYPES:
        raise ValueError(f"Unknown provider event type: {event_type}")
    if event_type == CONTENT_DELTA:
        text = event.get("text")
        if not isinstance(text, str):
            raise ValueError("content_delta events must include text.")
    if event_type == TOOL_CALLS:
        tool_calls = event.get("tool_calls")
        if not isinstance(tool_calls, list) or not all(isinstance(call, ToolCall) for call in tool_calls):
            raise ValueError("tool_calls events must include a list of ToolCall.")
    if event_type == TOKEN_USAGE:
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            value = event.get(key)
            if value is not None and (not isinstance(value, int) or isinstance(value, bool)):
                raise ValueError("token_usage values must be integers or None.")
