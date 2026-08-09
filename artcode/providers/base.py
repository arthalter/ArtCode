from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from .events import ProviderEvent


@dataclass(frozen=True)
class ProviderRequest:
    messages: tuple[dict[str, Any], ...]
    tools: tuple[dict[str, Any], ...] | None = None
    max_output_tokens: int | None = None
    thinking_enabled: bool | None = None

    def __post_init__(self) -> None:
        if self.max_output_tokens is not None and (
            isinstance(self.max_output_tokens, bool)
            or not isinstance(self.max_output_tokens, int)
            or self.max_output_tokens <= 0
        ):
            raise ValueError("max_output_tokens must be a positive integer or None")
        if self.thinking_enabled is not None and not isinstance(self.thinking_enabled, bool):
            raise TypeError("thinking_enabled must be a boolean or None")

    @classmethod
    def from_parts(
        cls,
        messages: Sequence[dict[str, Any]],
        tools: Sequence[dict[str, Any]] | None = None,
        *,
        max_output_tokens: int | None = None,
        thinking_enabled: bool | None = None,
    ) -> "ProviderRequest":
        return cls(
            messages=tuple(dict(message) for message in messages),
            tools=None if tools is None else tuple(dict(tool) for tool in tools),
            max_output_tokens=max_output_tokens,
            thinking_enabled=thinking_enabled,
        )


class StreamingProvider(Protocol):
    def stream(self, request: ProviderRequest) -> AsyncIterator[ProviderEvent]:
        ...
