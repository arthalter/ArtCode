from __future__ import annotations

import json

import httpx
import pytest

from artcode.config import ArtCodeConfig, ThinkingConfig
from artcode.errors import (
    AuthenticationError,
    ContextWindowExceededError,
    ModelError,
    ThinkingModeUnsupportedError,
)
from artcode.providers.base import ProviderRequest
from artcode.providers.deepseek import (
    DeepSeekChatProvider,
    _events_from_sse_data,
    build_provider_payload,
    map_http_error,
)
from artcode.providers.events import (
    ContentDelta,
    ReasoningDelta,
    StreamCompleted,
    TokenUsage,
    UsageReported,
)
from artcode.providers.tool_calls import ToolCallAccumulator

pytestmark = pytest.mark.ch10_5


def config(enabled: bool = False) -> ArtCodeConfig:
    return ArtCodeConfig(
        protocol="openai",
        model="deepseek-v4-flash",
        base_url="https://api.deepseek.com",
        api_key="sk-probe-secret",
        thinking=ThinkingConfig(enabled),
    )


@pytest.mark.parametrize(
    ("configured", "override", "expected"),
    [
        (False, None, "disabled"),
        (True, None, "enabled"),
        (False, True, "enabled"),
        (True, False, "disabled"),
    ],
    ids=("off-default", "on-default", "force-on", "force-off"),
)
def test_payload_expresses_thinking_state(configured: bool, override: bool | None, expected: str) -> None:
    payload = build_provider_payload(
        config(configured),
        ProviderRequest.from_parts([{"role": "user", "content": "hi"}], thinking_enabled=override),
    )
    assert payload["thinking"] == {"type": expected}
    assert ("reasoning_effort" in payload) is (expected == "enabled")


@pytest.mark.parametrize(
    ("thinking", "with_tools", "has_choice"),
    [
        (False, False, False),
        (True, False, False),
        (False, True, True),
        (True, True, False),
    ],
    ids=("plain-off", "plain-on", "tools-off", "tools-on"),
)
def test_payload_tool_choice_matches_deepseek_thinking_contract(
    thinking: bool, with_tools: bool, has_choice: bool
) -> None:
    tools = ({"type": "function", "function": {"name": "read_file"}},) if with_tools else None
    payload = build_provider_payload(config(thinking), ProviderRequest(({"role": "user", "content": "x"},), tools))
    assert ("tools" in payload) is with_tools
    assert ("tool_choice" in payload) is has_choice


@pytest.mark.parametrize("value", [1, 2, 8_192, 32_768, 384_000])
def test_positive_output_limits_are_forwarded(value: int) -> None:
    request = ProviderRequest.from_parts([], max_output_tokens=value)
    assert build_provider_payload(config(), request)["max_tokens"] == value


@pytest.mark.parametrize(
    "value",
    [0, -1, -999, True, False, 1.5, "10", object()],
    ids=("zero", "minus-one", "negative", "true", "false", "float", "string", "object"),
)
def test_invalid_output_limits_are_rejected(value) -> None:
    with pytest.raises((TypeError, ValueError)):
        ProviderRequest((), max_output_tokens=value)


@pytest.mark.parametrize(
    ("status", "body", "kind"),
    [
        (401, "unauthorized", AuthenticationError),
        (403, "forbidden", AuthenticationError),
        (400, "context_length_exceeded", ContextWindowExceededError),
        (400, "maximum context length", ContextWindowExceededError),
        (422, "too many tokens", ContextWindowExceededError),
        (400, "thinking is unsupported", ThinkingModeUnsupportedError),
        (400, "bad reasoning_effort", ThinkingModeUnsupportedError),
        (400, "bad request", ModelError),
        (404, "model missing", ModelError),
        (422, "invalid", ModelError),
        (429, "rate limited", ModelError),
        (500, "server", ModelError),
        (502, "gateway", ModelError),
        (503, "unavailable", ModelError),
        (599, "custom", ModelError),
    ],
    ids=(
        "auth-401", "auth-403", "context-code", "context-maximum", "context-tokens",
        "thinking", "reasoning", "bad-400", "missing-404", "invalid-422",
        "rate", "server", "gateway", "unavailable", "custom",
    ),
)
def test_http_error_matrix(status: int, body: str, kind: type[Exception]) -> None:
    error = map_http_error(status, body + " sk-probe-secret", ("sk-probe-secret",))
    assert isinstance(error, kind)
    assert "sk-probe-secret" not in str(error)


@pytest.mark.parametrize(
    ("delta", "event_type", "value"),
    [
        ({"content": "a"}, ContentDelta, "a"),
        ({"content": "中文"}, ContentDelta, "中文"),
        ({"reasoning_content": "r"}, ReasoningDelta, "r"),
        ({"reasoning_content": "推理"}, ReasoningDelta, "推理"),
        ({"content": ""}, None, None),
        ({"reasoning_content": ""}, None, None),
    ],
    ids=("content", "content-unicode", "reasoning", "reasoning-unicode", "empty-content", "empty-reasoning"),
)
def test_sse_delta_to_typed_event(delta: dict, event_type, value) -> None:
    data = json.dumps({"choices": [{"delta": delta, "finish_reason": None}]})
    events, finish = _events_from_sse_data(data, ToolCallAccumulator())
    assert finish is None
    if event_type is None:
        assert events == []
    else:
        assert isinstance(events[0], event_type)
        assert events[0].text == value


@pytest.mark.parametrize("finish", ["stop", "length", "tool_calls", "content_filter", "cancelled"])
def test_finish_reason_is_preserved(finish: str) -> None:
    events, observed = _events_from_sse_data(
        json.dumps({"choices": [{"delta": {}, "finish_reason": finish}]}),
        ToolCallAccumulator(),
    )
    assert events == []
    assert observed == finish


@pytest.mark.parametrize(
    ("usage", "expected"),
    [
        ({"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7}, (3, 4, 7, None, None)),
        ({"prompt_tokens": 10, "prompt_cache_hit_tokens": 7, "prompt_cache_miss_tokens": 3}, (10, None, None, 7, 3)),
        ({"prompt_tokens": 10, "prompt_tokens_details": {"cached_tokens": 6}}, (10, None, None, 6, 4)),
        ({"prompt_tokens": True, "completion_tokens": "4"}, (None, None, None, None, None)),
        ({}, (None, None, None, None, None)),
    ],
    ids=("basic", "deepseek-cache", "openai-cache", "bad-types", "empty"),
)
def test_usage_shapes_become_token_usage(usage: dict, expected: tuple) -> None:
    events, _ = _events_from_sse_data(json.dumps({"choices": [], "usage": usage}), ToolCallAccumulator())
    assert events == [UsageReported(TokenUsage(*expected))]


async def test_provider_close_is_idempotent() -> None:
    provider = DeepSeekChatProvider(config(), transport=httpx.MockTransport(lambda request: httpx.Response(200)))
    await provider.close()
    await provider.close()
    assert provider._closed is True


async def test_injected_client_remains_owned_by_caller() -> None:
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200)))
    provider = DeepSeekChatProvider(config(), client=client)
    await provider.close()
    assert client.is_closed is False
    await client.aclose()


def test_client_and_transport_cannot_both_be_injected() -> None:
    client = httpx.AsyncClient()
    try:
        with pytest.raises(ValueError, match="cannot both"):
            DeepSeekChatProvider(config(), transport=httpx.MockTransport(lambda request: httpx.Response(200)), client=client)
    finally:
        import asyncio

        asyncio.run(client.aclose())


async def test_stream_after_close_is_rejected() -> None:
    provider = DeepSeekChatProvider(config(), transport=httpx.MockTransport(lambda request: httpx.Response(200)))
    await provider.close()
    with pytest.raises(RuntimeError, match="closed"):
        [event async for event in provider.stream(ProviderRequest.from_parts([]))]


@pytest.mark.parametrize(
    "field",
    ["prompt_tokens", "completion_tokens", "total_tokens", "cached_tokens", "cache_miss_tokens"],
    ids=("prompt", "completion", "total", "cached", "miss"),
)
def test_each_token_usage_field_rejects_boolean(field: str) -> None:
    with pytest.raises(TypeError, match="integers or None"):
        TokenUsage(**{field: True})


@pytest.mark.parametrize("value", [1, 0, "true", []], ids=("one", "zero", "string", "list"))
def test_provider_request_rejects_non_boolean_thinking_override(value) -> None:
    with pytest.raises(TypeError, match="thinking_enabled"):
        ProviderRequest((), thinking_enabled=value)
