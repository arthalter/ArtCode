from __future__ import annotations

import json

from hypothesis import given, strategies as st
import pytest

from artcode.errors import StreamInterruptedError
from artcode.providers.deepseek import _events_from_sse_data
from artcode.providers.sse import SSEDecoder
from artcode.providers.tool_calls import ToolCallAccumulator
from tests.fixtures.sse import split_bytes

pytestmark = [pytest.mark.ch10_5, pytest.mark.property]
safe_text = st.text(
    alphabet=st.characters(exclude_categories=("Cs",), exclude_characters="\r\n"),
    max_size=100,
)


@given(safe_text)
def test_byte_stream_round_trip_for_arbitrary_unicode(text: str) -> None:
    payload = f"data: {text}\n\n".encode()
    cuts = tuple(range(1, len(payload)))
    chunks = split_bytes(payload, cuts) if len(payload) > 1 else (payload,)
    decoder = SSEDecoder()
    events = []
    for chunk in chunks:
        events.extend(decoder.feed_bytes(chunk))
    events.extend(decoder.close_bytes())
    assert [event.data for event in events] == [text]


@given(st.lists(safe_text.map(lambda value: value[:30]), min_size=1, max_size=10))
def test_multiple_data_lines_preserve_order(lines: list[str]) -> None:
    decoder = SSEDecoder()
    events = []
    for line in lines:
        events.extend(decoder.feed(f"data: {line}"))
    events.extend(decoder.feed(""))
    assert events[0].data == "\n".join(lines)


@given(st.permutations([0, 1, 2]))
def test_interleaved_tool_indices_finish_in_index_order(order) -> None:
    accumulator = ToolCallAccumulator()
    for index in order:
        accumulator.add_delta([{"index": index, "id": f"c{index}", "function": {"name": f"t{index}", "arguments": "{}"}}])
    assert [call.name for call in accumulator.finish()] == ["t0", "t1", "t2"]


@given(st.text(min_size=1).filter(lambda value: not value.lstrip().startswith(("{", "[", '"'))))
def test_non_json_sse_payload_is_always_rejected(data: str) -> None:
    with pytest.raises(StreamInterruptedError):
        _events_from_sse_data(data, ToolCallAccumulator())


@pytest.mark.parametrize(
    "delta",
    [
        [{}],
        [{"index": -1}],
        [{"index": True}],
        [{"index": "0"}],
        [{"index": 0, "id": 3}],
        [{"index": 0, "function": "bad"}],
        [{"index": 0, "function": {"name": 3}}],
        [{"index": 0, "function": {"arguments": {}}}],
        ["bad"],
    ],
    ids=("missing", "negative", "boolean", "string", "id", "function", "name", "arguments", "item"),
)
def test_invalid_tool_delta_shapes_fail_closed(delta) -> None:
    with pytest.raises(ValueError):
        ToolCallAccumulator().add_delta(delta)
