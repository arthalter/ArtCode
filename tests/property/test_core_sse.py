from __future__ import annotations

from hypothesis import given, strategies as st

from artcode._model.sse import SSEDecoder


SAFE_TEXT = st.text(
    alphabet=st.characters(exclude_categories=("Cs",), exclude_characters="\r\n"),
    max_size=100,
)


@given(SAFE_TEXT, st.lists(st.integers(min_value=1, max_value=8), max_size=20))
def test_arbitrary_utf8_chunking_preserves_sse_data(text: str, chunk_sizes: list[int]) -> None:
    payload = f"data: {text}\n\n".encode("utf-8")
    decoder = SSEDecoder()
    events = []
    cursor = 0
    for size in chunk_sizes:
        events.extend(decoder.feed_bytes(payload[cursor : cursor + size]))
        cursor += size
    events.extend(decoder.feed_bytes(payload[cursor:]))
    events.extend(decoder.close_bytes())
    assert [event.data for event in events] == [text]


@given(st.lists(SAFE_TEXT, min_size=1, max_size=8))
def test_multiple_data_lines_keep_order(lines: list[str]) -> None:
    decoder = SSEDecoder()
    events = []
    for line in lines:
        events.extend(decoder.feed(f"data: {line}"))
    events.extend(decoder.feed(""))
    assert events[0].data == "\n".join(lines)
