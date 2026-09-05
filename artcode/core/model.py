"""Public Model Interface independent of any Provider protocol."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
import json
from typing import Protocol, TypeAlias, runtime_checkable


class ModelFailure(RuntimeError):
    category = "model"


class AuthenticationFailure(ModelFailure):
    category = "authentication"


class NetworkFailure(ModelFailure):
    category = "network"


class TimeoutFailure(ModelFailure):
    category = "timeout"


class ContextWindowFailure(ModelFailure):
    category = "context_window"


class UnsupportedThinkingFailure(ModelFailure):
    category = "unsupported_thinking"


class ProtocolFailure(ModelFailure):
    category = "protocol"


@dataclass(frozen=True, slots=True, repr=False)
class ProtocolMetadata:
    """Provider-owned bytes that callers must store and return unchanged."""

    envelope: bytes

    def __post_init__(self) -> None:
        if not isinstance(self.envelope, bytes):
            raise TypeError("ProtocolMetadata envelope must be bytes")

    def __repr__(self) -> str:
        return "<ProtocolMetadata opaque>"


@dataclass(frozen=True, slots=True)
class ToolRequest:
    id: str
    name: str
    arguments_json: str

    def __post_init__(self) -> None:
        if not self.id or not self.name:
            raise ValueError("Tool request id and name must be non-empty")
        try:
            arguments = json.loads(self.arguments_json)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("Tool request arguments must be valid JSON") from exc
        if not isinstance(arguments, dict):
            raise ValueError("Tool request arguments must be a JSON object")


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    description: str
    parameters_json: str

    def __post_init__(self) -> None:
        if not self.name or not self.description:
            raise ValueError("Tool name and description must be non-empty")
        try:
            parameters = json.loads(self.parameters_json)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("Tool parameters must be valid JSON") from exc
        if not isinstance(parameters, dict):
            raise ValueError("Tool parameters must be a JSON object")


@dataclass(frozen=True, slots=True)
class ModelMessage:
    role: str
    content: str | None
    tool_requests: tuple[ToolRequest, ...] = ()
    tool_request_id: str | None = None
    metadata: ProtocolMetadata | None = None

    def __post_init__(self) -> None:
        if self.role not in {"system", "user", "assistant", "tool"}:
            raise ValueError(f"Unknown model message role: {self.role}")
        if self.content is not None and not isinstance(self.content, str):
            raise TypeError("Model message content must be text or None")
        if self.role in {"system", "user"} and self.content is None:
            raise ValueError(f"{self.role} message requires content")
        if self.role == "tool" and not self.tool_request_id:
            raise ValueError("tool message requires tool_request_id")
        if self.role != "tool" and self.tool_request_id is not None:
            raise ValueError("only tool messages may carry tool_request_id")
        if self.role != "assistant" and (self.tool_requests or self.metadata is not None):
            raise ValueError("only assistant messages may carry tool requests or protocol metadata")


@dataclass(frozen=True, slots=True)
class ModelRequest:
    prompt: tuple[ModelMessage, ...]
    tools: tuple[ToolDefinition, ...] = ()
    max_output_tokens: int | None = None
    thinking_enabled: bool | None = None
    model: str | None = None

    def __post_init__(self) -> None:
        if not self.prompt or not all(isinstance(item, ModelMessage) for item in self.prompt):
            raise ValueError("Model request requires a non-empty immutable prompt")
        if self.max_output_tokens is not None and (
            isinstance(self.max_output_tokens, bool)
            or not isinstance(self.max_output_tokens, int)
            or self.max_output_tokens <= 0
        ):
            raise ValueError("max_output_tokens must be a positive integer")
        if self.thinking_enabled is not None and not isinstance(self.thinking_enabled, bool):
            raise TypeError("thinking_enabled must be bool or None")
        if self.model is not None and (not isinstance(self.model, str) or not self.model.strip()):
            raise ValueError("model override must be non-empty")


@dataclass(frozen=True, slots=True)
class ModelSettings:
    model: str
    base_url: str
    api_key: str
    thinking_enabled: bool = False
    connect_timeout_seconds: float = 10.0
    read_timeout_seconds: float = 60.0

    def __post_init__(self) -> None:
        if not all(isinstance(value, str) and value.strip() for value in (self.model, self.base_url, self.api_key)):
            raise ValueError("Model settings require model, base_url, and api_key")
        if not isinstance(self.thinking_enabled, bool):
            raise TypeError("thinking_enabled must be bool")
        if self.connect_timeout_seconds <= 0 or self.read_timeout_seconds <= 0:
            raise ValueError("Model timeouts must be positive")


@dataclass(frozen=True, slots=True)
class TextDelta:
    text: str

    def __post_init__(self) -> None:
        if not isinstance(self.text, str) or not self.text:
            raise ValueError("TextDelta requires non-empty text")


@dataclass(frozen=True, slots=True)
class ToolRequests:
    requests: tuple[ToolRequest, ...]
    metadata: ProtocolMetadata | None = None

    def __post_init__(self) -> None:
        if not self.requests or not all(isinstance(item, ToolRequest) for item in self.requests):
            raise ValueError("ToolRequests requires one or more ToolRequest values")


@dataclass(frozen=True, slots=True)
class Usage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    cached_tokens: int | None = None
    cache_miss_tokens: int | None = None

    def __post_init__(self) -> None:
        for value in (
            self.input_tokens,
            self.output_tokens,
            self.total_tokens,
            self.cached_tokens,
            self.cache_miss_tokens,
        ):
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 0
            ):
                raise TypeError("Usage values must be non-negative integers or None")


@dataclass(frozen=True, slots=True)
class Completed:
    finish_reason: str | None

    def __post_init__(self) -> None:
        if self.finish_reason is not None and not isinstance(self.finish_reason, str):
            raise TypeError("finish_reason must be text or None")


ModelEvent: TypeAlias = TextDelta | ToolRequests | Usage | Completed


@runtime_checkable
class Model(Protocol):
    def stream(self, request: ModelRequest) -> AsyncIterator[ModelEvent]: ...

    async def close(self) -> None: ...


__all__ = [
    "AuthenticationFailure",
    "Completed",
    "ContextWindowFailure",
    "Model",
    "ModelEvent",
    "ModelFailure",
    "ModelMessage",
    "ModelRequest",
    "ModelSettings",
    "NetworkFailure",
    "ProtocolFailure",
    "ProtocolMetadata",
    "TextDelta",
    "TimeoutFailure",
    "ToolDefinition",
    "ToolRequest",
    "ToolRequests",
    "UnsupportedThinkingFailure",
    "Usage",
]
