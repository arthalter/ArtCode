from __future__ import annotations

import json

import pytest

from tests.fixtures.filesystem import FaultyAtomicWriter, InjectedFilesystemFailure
from tests.fixtures.jsonl import corrupt_line, encode_jsonl
from tests.fixtures.sse import split_bytes, sse_event

pytestmark = [pytest.mark.ch10_5, pytest.mark.fault]


def test_split_bytes_preserves_payload() -> None:
    payload = sse_event('{"value":"中文"}')
    assert b"".join(split_bytes(payload, (1, 5, len(payload) - 1))) == payload


def test_split_bytes_normalizes_duplicate_unsorted_cuts() -> None:
    assert split_bytes(b"abcdef", (4, 2, 2)) == (b"ab", b"cd", b"ef")


def test_split_bytes_rejects_boundary_cut() -> None:
    with pytest.raises(ValueError, match="inside"):
        split_bytes(b"abc", (0,))


def test_sse_event_keeps_multiple_data_lines() -> None:
    assert sse_event("one", "two", event="message") == b"event: message\ndata: one\ndata: two\n\n"


def test_jsonl_fixture_round_trips_unicode() -> None:
    payload = encode_jsonl(({"text": "空 白"}, {"text": "第二行"}))
    assert [json.loads(line) for line in payload.splitlines()] == [
        {"text": "空 白"},
        {"text": "第二行"},
    ]


def test_jsonl_fixture_can_append_incomplete_tail() -> None:
    payload = encode_jsonl(({"ok": 1},), incomplete_tail=b'{"partial"')
    assert payload.endswith(b'{"partial"')
    assert payload.count(b"\n") == 1


def test_jsonl_fixture_corrupts_only_selected_line() -> None:
    payload = encode_jsonl(({"n": 1}, {"n": 2}, {"n": 3}))
    corrupted = corrupt_line(payload, 1)
    lines = corrupted.splitlines()
    assert json.loads(lines[0]) == {"n": 1}
    assert lines[1] == b"{broken}"
    assert json.loads(lines[2]) == {"n": 3}


@pytest.mark.parametrize("stage", FaultyAtomicWriter.STAGES, ids=FaultyAtomicWriter.STAGES)
def test_faulty_atomic_writer_fails_at_exact_stage(stage: str, tmp_path) -> None:
    writer = FaultyAtomicWriter(stage)
    with pytest.raises(InjectedFilesystemFailure, match=stage):
        for current in FaultyAtomicWriter.STAGES:
            writer.visit(current, tmp_path / "target.txt")
    assert writer.visited[-1] == f"{stage}:target.txt"
