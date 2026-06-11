from __future__ import annotations

import pytest

from artcode.providers.events import CONTENT_DELTA, DONE, TOOL_CALLS, content_delta_event, done_event, tool_calls_event, validate_event
from artcode.providers.tool_calls import ToolCall


def test_content_delta_event_contains_text() -> None:
    assert content_delta_event("hi") == {"type": CONTENT_DELTA, "text": "hi"}


def test_done_event_marks_end() -> None:
    assert done_event() == {"type": DONE}


def test_tool_calls_event_contains_calls() -> None:
    call = ToolCall(id="call_1", name="read_file", arguments_json='{"path":"a.txt"}')

    assert tool_calls_event([call]) == {"type": TOOL_CALLS, "tool_calls": [call]}


def test_invalid_event_type_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown provider event type"):
        validate_event({"type": "unknown"})


def test_content_delta_requires_text() -> None:
    with pytest.raises(ValueError, match="must include text"):
        validate_event({"type": CONTENT_DELTA})


def test_tool_calls_requires_tool_call_list() -> None:
    with pytest.raises(ValueError, match="must include a list"):
        validate_event({"type": TOOL_CALLS, "tool_calls": ["not-a-call"]})
