from __future__ import annotations

from artcode.providers.sse import SSEDecoder, parse_sse_lines


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


def test_byte_decoder_flushes_unterminated_utf8_event() -> None:
    decoder = SSEDecoder()
    payload = "data: 中文".encode()

    assert decoder.feed_bytes(payload[:8]) == []
    events = decoder.feed_bytes(payload[8:])
    assert events == []
    assert decoder.close_bytes()[0].data == "中文"


def test_bytes_and_data_without_space_are_supported() -> None:
    events = list(parse_sse_lines([b"data:value\r\n", b"\r\n"]))

    assert events[0].data == "value"
