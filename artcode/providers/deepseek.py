from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx

from artcode.config import ArtCodeConfig
from artcode.errors import (
    AuthenticationError,
    ContextWindowExceededError,
    ModelError,
    NetworkError,
    StreamInterruptedError,
    ThinkingModeUnsupportedError,
    TimeoutError,
    scrub_secrets,
)

from .base import ProviderRequest, ProviderRequestOptions
from .events import (
    ContentDelta,
    ProviderEvent,
    ReasoningDelta,
    StreamCompleted,
    ToolCallsCompleted,
    TokenUsage,
    UsageReported,
)
from .sse import SSEDecoder
from .tool_calls import ToolCallAccumulator


CONNECT_TIMEOUT_SECONDS = 10.0
READ_TIMEOUT_SECONDS = 60.0


class DeepSeekChatProvider:
    def __init__(
        self,
        config: ArtCodeConfig,
        transport: httpx.AsyncBaseTransport | None = None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if client is not None and transport is not None:
            raise ValueError("client and transport cannot both be provided")
        self.config = config
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=provider_timeout(),
            transport=transport,
        )
        self._closed = False

    async def stream(self, request: ProviderRequest) -> AsyncIterator[ProviderEvent]:
        if self._closed:
            raise RuntimeError("DeepSeek provider is closed")
        payload = build_provider_payload(self.config, request)
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        try:
            async with self._client.stream(
                "POST",
                chat_completions_url(self.config.base_url),
                headers=headers,
                json=payload,
            ) as response:
                if response.status_code >= 400:
                    body = (await response.aread()).decode("utf-8", errors="replace")
                    raise map_http_error(response.status_code, body, (self.config.api_key,))
                async for event in self._iter_stream_events(response):
                    yield event
        except asyncio.CancelledError:
            raise
        except httpx.TimeoutException as exc:
            raise TimeoutError(
                "请求 DeepSeek 超时。",
                f"连接超时为 {int(CONNECT_TIMEOUT_SECONDS)} 秒，读取超时为 {int(READ_TIMEOUT_SECONDS)} 秒；请检查网络或稍后重试。",
            ) from exc
        except (httpx.ConnectError, httpx.NetworkError) as exc:
            raise NetworkError("无法连接 DeepSeek API。", "请检查网络、代理或 base_url。") from exc
        except (httpx.RemoteProtocolError, httpx.ReadError, httpx.DecodingError) as exc:
            raise StreamInterruptedError("流式响应中途断开。", "本轮回复没有写入上下文，请稍后重试。") from exc

    async def stream_chat(
        self,
        messages: Sequence[dict[str, Any]],
        tools: Sequence[dict[str, Any]] | None = None,
        *,
        options: ProviderRequestOptions | None = None,
    ) -> AsyncIterator[ProviderEvent]:
        """Transitional compatibility entry; production callers use stream(request)."""

        request = ProviderRequest.from_parts(
            messages,
            tools,
            max_output_tokens=options.max_output_tokens if options else None,
            thinking_enabled=options.thinking_enabled if options else None,
        )
        async for event in self.stream(request):
            yield event

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._owns_client:
            await self._client.aclose()

    async def _iter_stream_events(self, response: httpx.Response) -> AsyncIterator[ProviderEvent]:
        decoder = SSEDecoder()
        tool_calls = ToolCallAccumulator()
        finish_reason: str | None = None

        async for line in response.aiter_lines():
            for sse_event in decoder.feed(line):
                if sse_event.done:
                    if tool_calls.has_calls():
                        try:
                            yield ToolCallsCompleted(tool_calls.finish())
                        except ValueError as exc:
                            raise StreamInterruptedError("工具调用流无法组装。", str(exc)) from exc
                    yield StreamCompleted(finish_reason)
                    return
                events, observed_finish = _events_from_sse_data(sse_event.data, tool_calls)
                if observed_finish is not None:
                    finish_reason = observed_finish
                for event in events:
                    yield event

        for sse_event in decoder.close():
            if sse_event.done:
                if tool_calls.has_calls():
                    try:
                        yield ToolCallsCompleted(tool_calls.finish())
                    except ValueError as exc:
                        raise StreamInterruptedError("工具调用流无法组装。", str(exc)) from exc
                yield StreamCompleted(finish_reason)
                return
            events, observed_finish = _events_from_sse_data(sse_event.data, tool_calls)
            if observed_finish is not None:
                finish_reason = observed_finish
            for event in events:
                yield event

        raise StreamInterruptedError("流式响应意外结束。", "没有收到 [DONE] 结束事件。")


def chat_completions_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/chat/completions"


def provider_timeout() -> httpx.Timeout:
    return httpx.Timeout(
        timeout=None,
        connect=CONNECT_TIMEOUT_SECONDS,
        read=READ_TIMEOUT_SECONDS,
        write=10.0,
        pool=10.0,
    )


def build_provider_payload(config: ArtCodeConfig, request: ProviderRequest) -> dict[str, Any]:
    thinking_enabled = config.thinking.enabled
    if request.thinking_enabled is not None:
        thinking_enabled = request.thinking_enabled
    payload: dict[str, Any] = {
        "model": config.model,
        "messages": [dict(message) for message in request.messages],
        "stream": True,
        "stream_options": {"include_usage": True},
        "thinking": {"type": "enabled" if thinking_enabled else "disabled"},
    }
    if thinking_enabled:
        payload["reasoning_effort"] = "high"
    if request.tools is not None:
        payload["tools"] = [dict(tool) for tool in request.tools]
        if not thinking_enabled:
            payload["tool_choice"] = "auto"
    if request.max_output_tokens is not None:
        payload["max_tokens"] = request.max_output_tokens
    return payload


def build_request_payload(
    config: ArtCodeConfig,
    messages: Sequence[dict[str, Any]],
    tools: Sequence[dict[str, Any]] | None = None,
    *,
    options: ProviderRequestOptions | None = None,
) -> dict[str, Any]:
    return build_provider_payload(
        config,
        ProviderRequest.from_parts(
            messages,
            tools,
            max_output_tokens=options.max_output_tokens if options else None,
            thinking_enabled=options.thinking_enabled if options else None,
        ),
    )


def map_http_error(status_code: int, response_body: str, secrets: Sequence[str]) -> Exception:
    safe_body = scrub_secrets(response_body, secrets)
    if status_code in {401, 403}:
        return AuthenticationError("DeepSeek 认证失败。", "请检查 ~/.artcode/config.yml 中的 api_key 是否正确。")
    if _looks_like_context_window_error(safe_body):
        return ContextWindowExceededError(
            "模型上下文窗口已超限。",
            f"服务端返回 HTTP {status_code}：{safe_body}",
        )
    if _looks_like_thinking_error(safe_body):
        return ThinkingModeUnsupportedError(
            "DeepSeek 当前不接受 Thinking Mode 参数。",
            "请尝试关闭 thinking.enabled，或确认当前模型是否支持 Thinking Mode。",
        )
    if status_code in {400, 404, 422}:
        return ModelError("DeepSeek 请求或模型配置不可用。", f"服务端返回 HTTP {status_code}：{safe_body}")
    return ModelError("DeepSeek API 返回错误。", f"HTTP {status_code}：{safe_body}")


def _events_from_sse_data(
    data: str,
    tool_calls: ToolCallAccumulator,
) -> tuple[list[ProviderEvent], str | None]:
    try:
        payload = json.loads(data)
    except json.JSONDecodeError as exc:
        raise StreamInterruptedError("流式响应格式无法解析。", "DeepSeek 返回了非 JSON 的 SSE data。") from exc
    if not isinstance(payload, dict):
        raise StreamInterruptedError("流式响应结构异常。", "SSE data 顶层不是对象。")

    events: list[ProviderEvent] = []
    usage = payload.get("usage")
    if isinstance(usage, dict):
        prompt_tokens = _int_or_none(usage.get("prompt_tokens"))
        cached_tokens = _cache_hit_tokens(usage)
        events.append(
            UsageReported(
                TokenUsage(
                    prompt_tokens,
                    _int_or_none(usage.get("completion_tokens")),
                    _int_or_none(usage.get("total_tokens")),
                    cached_tokens,
                    _cache_miss_tokens(usage, prompt_tokens, cached_tokens),
                )
            )
        )

    choices = payload.get("choices")
    if not isinstance(choices, list):
        if isinstance(usage, dict):
            return events, None
        raise StreamInterruptedError("流式响应结构异常。", "SSE data 中缺少 choices。")

    finish_reason: str | None = None
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        observed = choice.get("finish_reason")
        if isinstance(observed, str):
            finish_reason = observed
        delta = choice.get("delta") or {}
        if not isinstance(delta, dict):
            continue
        reasoning = delta.get("reasoning_content")
        if isinstance(reasoning, str) and reasoning:
            events.append(ReasoningDelta(reasoning))
        content = delta.get("content")
        if isinstance(content, str) and content:
            events.append(ContentDelta(content))
        delta_tool_calls = delta.get("tool_calls")
        if isinstance(delta_tool_calls, list):
            try:
                tool_calls.add_delta(delta_tool_calls)
            except ValueError as exc:
                raise StreamInterruptedError("工具调用流无法组装。", str(exc)) from exc
    return events, finish_reason


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    return value if isinstance(value, int) else None


def _cache_hit_tokens(usage: dict[str, Any]) -> int | None:
    value = _int_or_none(usage.get("prompt_cache_hit_tokens"))
    if value is not None:
        return value
    details = usage.get("prompt_tokens_details")
    return _int_or_none(details.get("cached_tokens")) if isinstance(details, dict) else None


def _cache_miss_tokens(usage: dict[str, Any], prompt: int | None, cached: int | None) -> int | None:
    value = _int_or_none(usage.get("prompt_cache_miss_tokens"))
    if value is not None:
        return value
    if prompt is not None and cached is not None:
        return max(prompt - cached, 0)
    return None


def _looks_like_thinking_error(response_body: str) -> bool:
    lowered = response_body.lower()
    return "thinking" in lowered or "reasoning_effort" in lowered or "reasoning effort" in lowered


def _looks_like_context_window_error(response_body: str) -> bool:
    lowered = response_body.lower()
    return any(
        marker in lowered
        for marker in (
            "context_length_exceeded",
            "context length exceeded",
            "maximum context length",
            "max context length",
            "context window",
            "too many tokens",
        )
    )
