from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any


def encode_jsonl(records: Iterable[Mapping[str, Any]], *, incomplete_tail: bytes = b"") -> bytes:
    complete = b"".join(
        json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode() + b"\n"
        for record in records
    )
    return complete + incomplete_tail


def corrupt_line(payload: bytes, index: int, replacement: bytes = b"{broken}\n") -> bytes:
    lines = payload.splitlines(keepends=True)
    if index < 0 or index >= len(lines):
        raise IndexError(index)
    lines[index] = replacement
    return b"".join(lines)
