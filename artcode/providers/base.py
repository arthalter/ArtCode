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


@dataclass(frozen=True)
class ProviderRequestOptions:
    """Transitional input accepted by older internal callers until T14."""

    max_output_tokens: int | None = None
    thinking_enabled: bool | None = None


class StreamingProvider(Protocol):
    def stream(self, request: ProviderRequest) -> AsyncIterator[ProviderEvent]:
        ...


def stream_provider(provider: StreamingProvider, request: ProviderRequest) -> AsyncIterator[ProviderEvent]:
    stream = getattr(provider, "stream", None)
    if callable(stream):
        return stream(request)
    legacy = getattr(provider, "stream_chat", None)
    if not callable(legacy):
        raise TypeError("provider must implement stream(request)")
    messages = list(request.messages)
    tools = None if request.tools is None else list(request.tools)
    if request.max_output_tokens is None and request.thinking_enabled is None:
        return legacy(messages, tools)
    options = ProviderRequestOptions(request.max_output_tokens, request.thinking_enabled)
    return legacy(messages, tools, options=options)
