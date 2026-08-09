from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypeAlias

from .tool_calls import ToolCall


@dataclass(frozen=True)
class TokenUsage:
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    cached_tokens: int | None = None
    cache_miss_tokens: int | None = None

    def __post_init__(self) -> None:
        for value in (
            self.prompt_tokens,
            self.completion_tokens,
            self.total_tokens,
            self.cached_tokens,
            self.cache_miss_tokens,
        ):
            if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
                raise TypeError("token usage values must be integers or None")

    @classmethod
    def from_event_payload(cls, payload: dict[str, Any]) -> "TokenUsage":
        return cls(
            prompt_tokens=_optional_int(payload.get("prompt_tokens")),
            completion_tokens=_optional_int(payload.get("completion_tokens")),
            total_tokens=_optional_int(payload.get("total_tokens")),
            cached_tokens=_optional_int(payload.get("cached_tokens")),
            cache_miss_tokens=_optional_int(payload.get("cache_miss_tokens")),
        )

    def to_payload(self) -> dict[str, int | None]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "cached_tokens": self.cached_tokens,
            "cache_miss_tokens": self.cache_miss_tokens,
        }


@dataclass(frozen=True)
class ContentDelta:
    text: str

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise TypeError("text must be a string")


@dataclass(frozen=True)
class ReasoningDelta:
    text: str

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise TypeError("text must be a string")


@dataclass(frozen=True)
class ToolCallsCompleted:
    tool_calls: tuple[ToolCall, ...]

    def __post_init__(self) -> None:
        if not all(isinstance(call, ToolCall) for call in self.tool_calls):
            raise TypeError("tool_calls must contain ToolCall values")


@dataclass(frozen=True)
class UsageReported:
    usage: TokenUsage

    def __post_init__(self) -> None:
        if not isinstance(self.usage, TokenUsage):
            raise TypeError("usage must be TokenUsage")


@dataclass(frozen=True)
class StreamCompleted:
    finish_reason: str | None = None

    def __post_init__(self) -> None:
        if self.finish_reason is not None and not isinstance(self.finish_reason, str):
            raise TypeError("finish_reason must be a string or None")


ProviderEvent: TypeAlias = ContentDelta | ReasoningDelta | ToolCallsCompleted | UsageReported | StreamCompleted


def content_delta_event(text: str) -> ContentDelta:
    return ContentDelta(text)


def reasoning_delta_event(text: str) -> ReasoningDelta:
    return ReasoningDelta(text)


def tool_calls_event(tool_calls) -> ToolCallsCompleted:
    return ToolCallsCompleted(tuple(tool_calls))


def token_usage_event(
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    total_tokens: int | None = None,
    cached_tokens: int | None = None,
    cache_miss_tokens: int | None = None,
) -> UsageReported:
    return UsageReported(
        TokenUsage(prompt_tokens, completion_tokens, total_tokens, cached_tokens, cache_miss_tokens)
    )


def done_event(finish_reason: str | None = None) -> StreamCompleted:
    return StreamCompleted(finish_reason)


def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    return value if isinstance(value, int) else None
