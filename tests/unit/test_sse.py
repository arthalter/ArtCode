from __future__ import annotations

from artcode.providers.sse import parse_sse_lines


def test_single_data_event() -> None:
    events = list(parse_sse_lines(["data: hello", ""]))

    assert len(events) == 1
    assert events[0].data == "hello"
    assert events[0].done is False


def test_done_event() -> None:
    events = list(parse_sse_lines(["data: [DONE]", ""]))

    assert len(events) == 1
    assert events[0].done is True


def test_multiline_data_event_is_joined() -> None:
    events = list(parse_sse_lines(["data: first", "data: second", ""]))

    assert events[0].data == "first\nsecond"


def test_comment_lines_are_ignored() -> None:
    events = list(parse_sse_lines([": keepalive", "data: payload", ""]))

    assert events[0].data == "payload"


def test_no_auto_reconnect_fields_are_emitted() -> None:
    events = list(parse_sse_lines(["retry: 1000", "event: message", "data: payload", ""]))

    assert len(events) == 1
    assert events[0].data == "payload"
