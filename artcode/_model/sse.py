from __future__ import annotations

import codecs
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SSEEvent:
    data: str
    done: bool = False


class SSEDecoder:
    def __init__(self) -> None:
        self._data_lines: list[str] = []
        self._decoder = codecs.getincrementaldecoder("utf-8")()
        self._buffer = ""

    def feed(self, raw_line: str | bytes) -> list[SSEEvent]:
        line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
        line = line.rstrip("\r\n")
        if line == "":
            return self._flush()
        if line.startswith(":"):
            return []
        if line.startswith("data:"):
            value = line[5:]
            self._data_lines.append(value[1:] if value.startswith(" ") else value)
        return []

    def close(self) -> list[SSEEvent]:
        return self._flush()

    def feed_bytes(self, chunk: bytes) -> list[SSEEvent]:
        self._buffer += self._decoder.decode(chunk, final=False)
        events: list[SSEEvent] = []
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            events.extend(self.feed(line))
        return events

    def close_bytes(self) -> list[SSEEvent]:
        self._buffer += self._decoder.decode(b"", final=True)
        events: list[SSEEvent] = []
        if self._buffer:
            events.extend(self.feed(self._buffer))
            self._buffer = ""
        events.extend(self.close())
        return events

    def _flush(self) -> list[SSEEvent]:
        if not self._data_lines:
            return []
        data = "\n".join(self._data_lines)
        self._data_lines.clear()
        return [SSEEvent(data, done=data.strip() == "[DONE]")]
