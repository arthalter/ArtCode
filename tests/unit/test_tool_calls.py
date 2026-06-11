from __future__ import annotations

from artcode.providers.tool_calls import ToolCallAccumulator


def test_accumulator_joins_argument_fragments_by_index() -> None:
    accumulator = ToolCallAccumulator()

    accumulator.add_delta(
        [
            {
                "index": 0,
                "id": "call_1",
                "function": {"name": "read_file", "arguments": '{"pa'},
            }
        ]
    )
    accumulator.add_delta([{"index": 0, "function": {"arguments": 'th":"a.txt"}'}}])

    calls = accumulator.finish()
    assert len(calls) == 1
    assert calls[0].id == "call_1"
    assert calls[0].name == "read_file"
    assert calls[0].arguments_json == '{"path":"a.txt"}'


def test_accumulator_keeps_multiple_indices_in_order() -> None:
    accumulator = ToolCallAccumulator()

    accumulator.add_delta([{"index": 1, "id": "call_b", "function": {"name": "write_file", "arguments": "{}"}}])
    accumulator.add_delta([{"index": 0, "id": "call_a", "function": {"name": "read_file", "arguments": "{}"}}])

    calls = accumulator.finish()
    assert [call.id for call in calls] == ["call_a", "call_b"]


def test_accumulator_reports_presence() -> None:
    accumulator = ToolCallAccumulator()

    assert accumulator.has_calls() is False
    accumulator.add_delta([{"index": 0, "id": "call_1", "function": {"name": "read_file"}}])
    assert accumulator.has_calls() is True
