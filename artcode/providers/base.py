from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ProviderRequestOptions:
    max_output_tokens: int | None = None
    thinking_enabled: bool | None = None


class StreamingProvider(Protocol):
    def stream_chat(
        self,
        messages: Sequence[dict[str, Any]],
        tools: Sequence[dict[str, Any]] | None = None,
        *,
        options: ProviderRequestOptions | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        ...
