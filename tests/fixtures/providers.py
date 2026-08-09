from __future__ import annotations

from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ScriptedProvider:
    """A deterministic provider that exposes request and close lifecycle evidence."""

    streams: list[tuple[Any, ...]]
    requests: list[Any] = field(default_factory=list)
    close_count: int = 0

    @classmethod
    def from_streams(cls, streams: Iterable[Iterable[Any]]) -> "ScriptedProvider":
        return cls([tuple(stream) for stream in streams])

    async def stream(self, request: Any) -> AsyncIterator[Any]:
        self.requests.append(request)
        if not self.streams:
            raise AssertionError("no scripted provider stream remains")
        for event in self.streams.pop(0):
            if isinstance(event, BaseException):
                raise event
            yield event

    async def close(self) -> None:
        self.close_count += 1
