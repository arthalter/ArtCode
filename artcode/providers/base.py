from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Protocol


class StreamingProvider(Protocol):
    def stream_chat(self, messages: Sequence[dict[str, str]]) -> AsyncIterator[dict[str, str]]:
        ...
