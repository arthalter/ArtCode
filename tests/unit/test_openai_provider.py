from __future__ import annotations

import pytest

from artcode.config import ArtCodeConfig, ThinkingConfig
from artcode.errors import AuthenticationError, ContextWindowExceededError, ModelError, ThinkingModeUnsupportedError
from artcode.providers import ProviderRequest
from artcode.providers.events import StreamCompleted, ToolCallsCompleted, UsageReported
from artcode.providers.deepseek import (
    CONNECT_TIMEOUT_SECONDS,
    DeepSeekChatProvider,
    READ_TIMEOUT_SECONDS,
    build_provider_payload,
    chat_completions_url,
    map_http_error,
    provider_timeout,
)


def config(thinking_enabled: bool = False) -> ArtCodeConfig:
    return ArtCodeConfig(
        protocol="openai",
        model="deepseek-v4-flash",
        base_url="https://api.deepseek.com/",
        api_key="sk-secret-key",
        thinking=ThinkingConfig(enabled=thinking_enabled),
    )


def test_chat_completions_url_does_not_double_slash() -> None:
    assert chat_completions_url("https://api.deepseek.com/") == "https://api.deepseek.com/chat/completions"


def test_payload_without_thinking_explicitly_disables_thinking() -> None:
    payload = build_provider_payload(config(False), ProviderRequest.from_parts([{"role": "user", "content": "hi"}]))

    assert payload["stream"] is True
    assert payload["stream_options"] == {"include_usage": True}
    assert payload["thinking"] == {"type": "disabled"}
    assert "reasoning_effort" not in payload


def test_payload_with_thinking_maps_effort() -> None:
    payload = build_provider_payload(config(True), ProviderRequest.from_parts([{"role": "user", "content": "hi"}]))

    assert payload["thinking"] == {"type": "enabled"}
    assert payload["reasoning_effort"] == "high"


def test_payload_with_tools_adds_tool_choice() -> None:
    tools = [{"type": "function", "function": {"name": "read_file", "description": "read", "parameters": {}}}]

    payload = build_provider_payload(config(False), ProviderRequest.from_parts([{"role": "user", "content": "hi"}], tools))

    assert payload["tools"] == tools
    assert payload["tool_choice"] == "auto"


def test_payload_without_tools_omits_tool_fields() -> None:
    payload = build_provider_payload(config(False), ProviderRequest.from_parts([{"role": "user", "content": "hi"}], None))

    assert "tools" not in payload
    assert "tool_choice" not in payload


def test_request_model_override_is_forwarded_without_mutating_default_config() -> None:
    payload = build_provider_payload(
        config(False),
        ProviderRequest.from_parts([{"role": "user", "content": "hi"}], model="skill-model"),
    )

    assert payload["model"] == "skill-model"


def test_summary_options_limit_output_and_disable_thinking() -> None:
    payload = build_provider_payload(
        config(True),
        ProviderRequest.from_parts(
            [{"role": "user", "content": "hi"}],
            None,
            max_output_tokens=20_000,
            thinking_enabled=False,
        ),
    )

    assert payload["max_tokens"] == 20_000
    assert payload["thinking"] == {"type": "disabled"}
    assert "reasoning_effort" not in payload
    assert "tools" not in payload
    assert "tool_choice" not in payload


def test_provider_timeout_values() -> None:
    timeout = provider_timeout()

    assert timeout.connect == CONNECT_TIMEOUT_SECONDS
    assert timeout.read == READ_TIMEOUT_SECONDS


def test_http_errors_are_mapped_without_leaking_secret() -> None:
    error = map_http_error(400, "bad sk-secret-key", ["sk-secret-key"])

    assert isinstance(error, ModelError)
    assert "sk-secret-key" not in error.user_message


@pytest.mark.parametrize("status_code", [401, 403])
def test_auth_errors_are_mapped(status_code: int) -> None:
    assert isinstance(map_http_error(status_code, "unauthorized", []), AuthenticationError)


def test_thinking_errors_are_mapped() -> None:
    error = map_http_error(400, "unsupported reasoning_effort", [])

    assert isinstance(error, ThinkingModeUnsupportedError)


def test_context_window_errors_have_dedicated_type_and_are_redacted() -> None:
    error = map_http_error(
        400,
        "context_length_exceeded for sk-secret-key",
        ["sk-secret-key"],
    )

    assert isinstance(error, ContextWindowExceededError)
    assert "sk-secret-key" not in error.user_message


class FakeStreamResponse:
    def __init__(self, lines: list[str]) -> None:
        self._lines = lines

    async def aiter_lines(self):
        for line in self._lines:
            yield line


async def test_provider_stream_parses_tool_calls() -> None:
    provider = DeepSeekChatProvider(config(False))
    lines = [
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1","function":{"name":"read_file","arguments":"{\\"pa"}}]}}]}',
        "",
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"th\\":\\"a.txt\\"}"}}]}}]}',
        "",
        "data: [DONE]",
        "",
    ]

    events = [event async for event in provider._iter_stream_events(FakeStreamResponse(lines))]

    assert isinstance(events[0], ToolCallsCompleted)
    assert events[0].tool_calls[0].name == "read_file"
    assert events[0].tool_calls[0].arguments_json == '{"path":"a.txt"}'
    assert isinstance(events[-1], StreamCompleted)


async def test_provider_stream_parses_usage_event() -> None:
    provider = DeepSeekChatProvider(config(False))
    lines = [
        'data: {"choices":[],"usage":{"prompt_tokens":3,"completion_tokens":4,"total_tokens":7}}',
        "",
        "data: [DONE]",
        "",
    ]

    events = [event async for event in provider._iter_stream_events(FakeStreamResponse(lines))]

    assert isinstance(events[0], UsageReported)
    assert events[0].usage.total_tokens == 7
    assert events[0].usage.cached_tokens is None
    assert events[0].usage.cache_miss_tokens is None
    assert isinstance(events[-1], StreamCompleted)


async def test_provider_stream_parses_deepseek_cache_usage() -> None:
    provider = DeepSeekChatProvider(config(False))
    lines = [
        'data: {"choices":[],"usage":{"prompt_tokens":10,"prompt_cache_hit_tokens":7,"prompt_cache_miss_tokens":3,"completion_tokens":4,"total_tokens":14}}',
        "",
        "data: [DONE]",
        "",
    ]

    events = [event async for event in provider._iter_stream_events(FakeStreamResponse(lines))]

    assert isinstance(events[0], UsageReported)
    assert events[0].usage.cached_tokens == 7
    assert events[0].usage.cache_miss_tokens == 3


async def test_provider_stream_parses_openai_cached_tokens() -> None:
    provider = DeepSeekChatProvider(config(False))
    lines = [
        'data: {"choices":[],"usage":{"prompt_tokens":10,"prompt_tokens_details":{"cached_tokens":6},"completion_tokens":4,"total_tokens":14}}',
        "",
        "data: [DONE]",
        "",
    ]

    events = [event async for event in provider._iter_stream_events(FakeStreamResponse(lines))]

    assert isinstance(events[0], UsageReported)
    assert events[0].usage.cached_tokens == 6
    assert events[0].usage.cache_miss_tokens == 4
