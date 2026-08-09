from __future__ import annotations

import json

import httpx
import pytest

from artcode.config import ArtCodeConfig, ThinkingConfig
from artcode.errors import AuthenticationError, ContextWindowExceededError, ModelError
from artcode.providers.base import ProviderRequest
from artcode.providers.deepseek import DeepSeekChatProvider
from artcode.providers.events import (
    ContentDelta,
    ReasoningDelta,
    StreamCompleted,
    ToolCallsCompleted,
    UsageReported,
)

pytestmark = pytest.mark.ch10_5


def config() -> ArtCodeConfig:
    return ArtCodeConfig("openai", "deepseek-v4-flash", "https://api.deepseek.com", "secret", ThinkingConfig())


def sse(*payloads: dict | str) -> bytes:
    lines = []
    for payload in payloads:
        value = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
        lines.append(f"data: {value}\n\n")
    return "".join(lines).encode()


@pytest.mark.parametrize(
    ("payloads", "types", "finish"),
    [
        (({"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]}, "[DONE]"), (ContentDelta, StreamCompleted), "stop"),
        (({"choices": [{"delta": {"reasoning_content": "r"}, "finish_reason": None}]}, "[DONE]"), (ReasoningDelta, StreamCompleted), None),
        (({"choices": [], "usage": {"total_tokens": 3}}, "[DONE]"), (UsageReported, StreamCompleted), None),
        (({"choices": [{"delta": {"content": "a"}, "finish_reason": None}]}, {"choices": [{"delta": {"content": "b"}, "finish_reason": "length"}]}, "[DONE]"), (ContentDelta, ContentDelta, StreamCompleted), "length"),
        (({"choices": [{"delta": {"reasoning_content": "r", "content": "c"}, "finish_reason": "stop"}]}, "[DONE]"), (ReasoningDelta, ContentDelta, StreamCompleted), "stop"),
        (({"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call", "function": {"name": "read_file", "arguments": "{}"}}]}, "finish_reason": "tool_calls"}]}, "[DONE]"), (ToolCallsCompleted, StreamCompleted), "tool_calls"),
        (({"choices": [{"delta": {"content": "中文"}, "finish_reason": "stop"}]}, "[DONE]"), (ContentDelta, StreamCompleted), "stop"),
        (({"choices": [], "usage": {"prompt_tokens": 10, "prompt_cache_hit_tokens": 8, "prompt_cache_miss_tokens": 2}}, "[DONE]"), (UsageReported, StreamCompleted), None),
        (({"choices": [{"delta": {}, "finish_reason": "content_filter"}]}, "[DONE]"), (StreamCompleted,), "content_filter"),
        (({"choices": [{"delta": {"content": ""}, "finish_reason": "stop"}]}, "[DONE]"), (StreamCompleted,), "stop"),
    ],
    ids=("text", "reasoning", "usage", "length", "mixed", "tool", "unicode", "cache", "filter", "empty"),
)
async def test_mock_http_stream_end_to_end(payloads, types, finish) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=sse(*payloads), headers={"content-type": "text/event-stream"})

    provider = DeepSeekChatProvider(config(), transport=httpx.MockTransport(handler))
    try:
        events = [event async for event in provider.stream(ProviderRequest.from_parts([{"role": "user", "content": "x"}]))]
    finally:
        await provider.close()
    assert tuple(type(event) for event in events) == types
    completed = next(event for event in events if isinstance(event, StreamCompleted))
    assert completed.finish_reason == finish


@pytest.mark.parametrize(
    ("status", "body", "kind"),
    [
        (401, "unauthorized secret", AuthenticationError),
        (400, "context_length_exceeded secret", ContextWindowExceededError),
        (404, "missing secret", ModelError),
        (500, "server secret", ModelError),
    ],
    ids=("auth", "context", "model", "server"),
)
async def test_mock_http_errors_are_typed_and_redacted(status: int, body: str, kind) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text=body)

    provider = DeepSeekChatProvider(config(), transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(kind) as captured:
            [event async for event in provider.stream(ProviderRequest.from_parts([]))]
    finally:
        await provider.close()
    assert "secret" not in str(captured.value)


async def test_multiple_requests_reuse_one_client_and_close_once() -> None:
    identities = []

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=sse({"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]}, "[DONE]"))

    provider = DeepSeekChatProvider(config(), transport=httpx.MockTransport(handler))
    for _ in range(3):
        identities.append(id(provider._client))
        [event async for event in provider.stream(ProviderRequest.from_parts([]))]
    await provider.close()
    assert len(set(identities)) == 1
    assert provider._client.is_closed is True
