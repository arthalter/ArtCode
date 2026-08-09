from __future__ import annotations

import pytest

from artcode.providers.events import (
    ContentDelta,
    ReasoningDelta,
    StreamCompleted,
    TokenUsage,
    ToolCallsCompleted,
    UsageReported,
    content_delta_event,
    done_event,
    reasoning_delta_event,
    token_usage_event,
    tool_calls_event,
)
from artcode.providers.tool_calls import ToolCall


def test_content_delta_event_contains_text() -> None:
    assert content_delta_event("hi") == ContentDelta("hi")


def test_done_event_marks_end() -> None:
    assert done_event() == StreamCompleted()


def test_tool_calls_event_contains_calls() -> None:
    call = ToolCall(id="call_1", name="read_file", arguments_json='{"path":"a.txt"}')
    assert tool_calls_event([call]) == ToolCallsCompleted((call,))


def test_reasoning_delta_is_distinct_from_visible_content() -> None:
    assert reasoning_delta_event("private") == ReasoningDelta("private")


def test_content_delta_requires_text() -> None:
    with pytest.raises(TypeError, match="string"):
        ContentDelta(None)  # type: ignore[arg-type]


def test_tool_calls_requires_tool_call_values() -> None:
    with pytest.raises(TypeError, match="ToolCall"):
        ToolCallsCompleted(("not-a-call",))  # type: ignore[arg-type]


def test_token_usage_event_contains_real_usage() -> None:
    assert token_usage_event(1, 2, 3, 4, 5) == UsageReported(TokenUsage(1, 2, 3, 4, 5))


def test_token_usage_requires_ints_or_none() -> None:
    with pytest.raises(TypeError, match="integers or None"):
        TokenUsage(prompt_tokens="1")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="integers or None"):
        TokenUsage(cached_tokens=True)
