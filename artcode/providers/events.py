from __future__ import annotations

CONTENT_DELTA = "content_delta"
DONE = "done"
VALID_EVENT_TYPES = {CONTENT_DELTA, DONE}


def content_delta_event(text: str) -> dict[str, str]:
    event = {"type": CONTENT_DELTA, "text": text}
    validate_event(event)
    return event


def done_event() -> dict[str, str]:
    event = {"type": DONE}
    validate_event(event)
    return event


def validate_event(event: dict[str, str]) -> None:
    event_type = event.get("type")
    if event_type not in VALID_EVENT_TYPES:
        raise ValueError(f"Unknown provider event type: {event_type}")
    if event_type == CONTENT_DELTA:
        text = event.get("text")
        if not isinstance(text, str):
            raise ValueError("content_delta events must include text.")
