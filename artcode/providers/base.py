from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any, Protocol


class StreamingProvider(Protocol):
    def stream_chat(
        self,
        messages: Sequence[dict[str, Any]],
        tools: Sequence[dict[str, Any]] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        ...
