from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Iterator


@dataclass(frozen=True)
class SSEEvent:
    data: str
    done: bool = False


class SSEDecoder:
    def __init__(self) -> None:
        self._data_lines: list[str] = []

    def feed(self, raw_line: str | bytes) -> list[SSEEvent]:
        line = _normalize_line(raw_line)
        if line == "":
            return self._flush()
        if line.startswith(":"):
            return []
        if line.startswith("data:"):
            self._data_lines.append(_field_value(line))
        return []

    def close(self) -> list[SSEEvent]:
        return self._flush()

    def _flush(self) -> list[SSEEvent]:
        if not self._data_lines:
            return []
        data = "\n".join(self._data_lines)
        self._data_lines.clear()
        return [SSEEvent(data=data, done=data.strip() == "[DONE]")]


def parse_sse_lines(lines: Iterable[str | bytes]) -> Iterator[SSEEvent]:
    decoder = SSEDecoder()
    for line in lines:
        yield from decoder.feed(line)
    yield from decoder.close()


def _normalize_line(raw_line: str | bytes) -> str:
    if isinstance(raw_line, bytes):
        raw_line = raw_line.decode("utf-8")
    return raw_line.rstrip("\r\n")


def _field_value(line: str) -> str:
    value = line[5:]
    if value.startswith(" "):
        return value[1:]
    return value
