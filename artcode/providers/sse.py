from __future__ import annotations

import codecs
from dataclasses import dataclass
from typing import Iterable, Iterator


@dataclass(frozen=True)
class SSEEvent:
    data: str
    done: bool = False


class SSEDecoder:
    def __init__(self) -> None:
        self._data_lines: list[str] = []
        self._utf8_decoder = codecs.getincrementaldecoder("utf-8")()
        self._byte_buffer = ""

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

    def feed_bytes(self, chunk: bytes) -> list[SSEEvent]:
        self._byte_buffer += self._utf8_decoder.decode(chunk, final=False)
        events: list[SSEEvent] = []
        while "\n" in self._byte_buffer:
            line, self._byte_buffer = self._byte_buffer.split("\n", 1)
            events.extend(self.feed(line))
        return events

    def close_bytes(self) -> list[SSEEvent]:
        self._byte_buffer += self._utf8_decoder.decode(b"", final=True)
        events: list[SSEEvent] = []
        if self._byte_buffer:
            events.extend(self.feed(self._byte_buffer))
            self._byte_buffer = ""
        events.extend(self.close())
        return events

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
