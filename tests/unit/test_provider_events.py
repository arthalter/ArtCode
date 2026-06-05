from __future__ import annotations

import pytest

from artcode.providers.events import CONTENT_DELTA, DONE, content_delta_event, done_event, validate_event


def test_content_delta_event_contains_text() -> None:
    assert content_delta_event("hi") == {"type": CONTENT_DELTA, "text": "hi"}


def test_done_event_marks_end() -> None:
    assert done_event() == {"type": DONE}


def test_invalid_event_type_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown provider event type"):
        validate_event({"type": "unknown"})


def test_content_delta_requires_text() -> None:
    with pytest.raises(ValueError, match="must include text"):
        validate_event({"type": CONTENT_DELTA})
