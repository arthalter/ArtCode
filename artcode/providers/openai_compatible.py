"""Transitional import compatibility; removed after all T14 callers migrate."""

from .deepseek import (
    CONNECT_TIMEOUT_SECONDS,
    READ_TIMEOUT_SECONDS,
    DeepSeekChatProvider,
    build_provider_payload,
    build_request_payload,
    chat_completions_url,
    map_http_error,
    provider_timeout,
)

OpenAICompatibleProvider = DeepSeekChatProvider

__all__ = [
    "CONNECT_TIMEOUT_SECONDS",
    "READ_TIMEOUT_SECONDS",
    "DeepSeekChatProvider",
    "OpenAICompatibleProvider",
    "build_provider_payload",
    "build_request_payload",
    "chat_completions_url",
    "map_http_error",
    "provider_timeout",
]
