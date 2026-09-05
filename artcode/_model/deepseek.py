from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
import json
from typing import Any

import httpx

from artcode.core.model import (
    AuthenticationFailure,
    Completed,
    ContextWindowFailure,
    ModelEvent,
    ModelMessage,
    ModelRequest,
    ModelSettings,
    NetworkFailure,
    ProtocolFailure,
    ProtocolMetadata,
    TextDelta,
    TimeoutFailure,
    ToolRequests,
    UnsupportedThinkingFailure,
    Usage,
)

from .redaction import scrub
from .sse import SSEDecoder
from .tool_calls import ToolCallAccumulator


class DeepSeekModel:
    """One-request OpenAI-compatible streaming Model adapter."""

    def __init__(
        self,
        settings: ModelSettings,
        transport: httpx.AsyncBaseTransport | None = None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if client is not None and transport is not None:
            raise ValueError("client and transport cannot both be provided")
        self.settings = settings
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            transport=transport,
            timeout=httpx.Timeout(
                None,
                connect=settings.connect_timeout_seconds,
                read=settings.read_timeout_seconds,
                write=10.0,
                pool=10.0,
            ),
        )
        self._closed = False

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelEvent]:
        if self._closed:
            raise RuntimeError("Model 已关闭。")
        payload = self._payload(request)
        headers = {
            "Authorization": f"Bearer {self.settings.api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        try:
            async with self._client.stream(
                "POST",
                f"{self.settings.base_url.rstrip('/')}/chat/completions",
                headers=headers,
                json=payload,
            ) as response:
                if response.status_code >= 400:
                    body = (await response.aread()).decode("utf-8", errors="replace")
                    raise self._http_failure(response.status_code, body)
                async for event in self._events(response):
                    yield event
        except asyncio.CancelledError:
            raise
        except (AuthenticationFailure, ContextWindowFailure, UnsupportedThinkingFailure, ProtocolFailure):
            raise
        except httpx.TimeoutException as exc:
            raise TimeoutFailure("模型请求超时。") from exc
        except httpx.ConnectError as exc:
            raise NetworkFailure("无法连接模型服务。") from exc
        except (httpx.RemoteProtocolError, httpx.ReadError, httpx.DecodingError) as exc:
            raise ProtocolFailure(f"模型流传输中断：{type(exc).__name__}") from exc
        except httpx.NetworkError as exc:
            raise NetworkFailure("模型网络请求失败。") from exc

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._owns_client:
            await self._client.aclose()

    async def _events(self, response: httpx.Response) -> AsyncIterator[ModelEvent]:
        decoder = SSEDecoder()
        calls = ToolCallAccumulator()
        reasoning: list[str] = []
        finish_reason: str | None = None
        produced_output = False
        async for line in response.aiter_lines():
            for item in decoder.feed(line):
                if item.done:
                    if calls.has_calls:
                        yield self._tool_requests(calls, reasoning)
                        produced_output = True
                    if not produced_output:
                        raise ProtocolFailure("模型返回空响应。")
                    yield Completed(finish_reason)
                    return
                events, observed = self._decode_data(item.data, calls, reasoning)
                if observed is not None:
                    finish_reason = observed
                for event in events:
                    if isinstance(event, (TextDelta, ToolRequests)):
                        produced_output = True
                    yield event
        for item in decoder.close():
            if item.done:
                if calls.has_calls:
                    yield self._tool_requests(calls, reasoning)
                    produced_output = True
                if not produced_output:
                    raise ProtocolFailure("模型返回空响应。")
                yield Completed(finish_reason)
                return
            events, observed = self._decode_data(item.data, calls, reasoning)
            if observed is not None:
                finish_reason = observed
            for event in events:
                if isinstance(event, (TextDelta, ToolRequests)):
                    produced_output = True
                yield event
        raise ProtocolFailure("模型流意外结束：未收到 [DONE]。")

    def _decode_data(
        self,
        data: str,
        calls: ToolCallAccumulator,
        reasoning: list[str],
    ) -> tuple[list[ModelEvent], str | None]:
        try:
            payload = json.loads(data)
        except json.JSONDecodeError as exc:
            raise ProtocolFailure("模型 SSE data 不是 JSON。") from exc
        if not isinstance(payload, dict):
            raise ProtocolFailure("模型 SSE data 顶层不是对象。")
        events: list[ModelEvent] = []
        usage_event: Usage | None = None
        usage = payload.get("usage")
        if isinstance(usage, dict):
            prompt = _optional_int(usage.get("prompt_tokens"))
            cached = _cache_hit(usage)
            miss = _optional_int(usage.get("prompt_cache_miss_tokens"))
            if miss is None and prompt is not None and cached is not None:
                miss = max(prompt - cached, 0)
            usage_event = Usage(
                prompt,
                _optional_int(usage.get("completion_tokens")),
                _optional_int(usage.get("total_tokens")),
                cached,
                miss,
            )
        choices = payload.get("choices")
        if not isinstance(choices, list):
            if isinstance(usage, dict):
                assert usage_event is not None
                return [usage_event], None
            raise ProtocolFailure("模型 SSE data 缺少 choices。")
        finish: str | None = None
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            observed = choice.get("finish_reason")
            if isinstance(observed, str):
                finish = observed
            delta = choice.get("delta") or {}
            if not isinstance(delta, dict):
                continue
            private = delta.get("reasoning_content")
            if isinstance(private, str) and private:
                reasoning.append(private)
            content = delta.get("content")
            if isinstance(content, str) and content:
                events.append(TextDelta(content))
            tool_delta = delta.get("tool_calls")
            if isinstance(tool_delta, list):
                try:
                    calls.add(tool_delta)
                except ValueError as exc:
                    raise ProtocolFailure(f"工具调用流无法组装：{exc}") from exc
        if usage_event is not None:
            events.append(usage_event)
        return events, finish

    @staticmethod
    def _tool_requests(calls: ToolCallAccumulator, reasoning: list[str]) -> ToolRequests:
        try:
            requests = calls.finish()
        except ValueError as exc:
            raise ProtocolFailure(f"工具调用流无法组装：{exc}") from exc
        metadata = None
        if reasoning:
            metadata = ProtocolMetadata(
                json.dumps(
                    {"reasoning_content": "".join(reasoning)},
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
            )
        return ToolRequests(requests, metadata)

    def _payload(self, request: ModelRequest) -> dict[str, Any]:
        thinking = self.settings.thinking_enabled if request.thinking_enabled is None else request.thinking_enabled
        model = request.model or self.settings.model
        payload: dict[str, Any] = {
            "model": model,
            "messages": [self._message(item) for item in request.prompt],
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if model.casefold() == "grok-4.6":
            payload["reasoning_effort"] = "high"
        else:
            payload["thinking"] = {"type": "enabled" if thinking else "disabled"}
            if thinking:
                payload["reasoning_effort"] = "high"
        if request.tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": item.name,
                        "description": item.description,
                        "parameters": json.loads(item.parameters_json),
                    },
                }
                for item in request.tools
            ]
            if not thinking and model.casefold() != "grok-4.6":
                payload["tool_choice"] = "auto"
        if request.max_output_tokens is not None:
            payload["max_tokens"] = request.max_output_tokens
        return payload

    @staticmethod
    def _message(message: ModelMessage) -> dict[str, Any]:
        payload: dict[str, Any] = {"role": message.role, "content": message.content}
        if message.role == "assistant" and message.tool_requests:
            payload["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": call.arguments_json},
                }
                for call in message.tool_requests
            ]
            if message.metadata is not None:
                try:
                    opaque = json.loads(message.metadata.envelope)
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise ProtocolFailure("Protocol Metadata envelope 无法解析。") from exc
                if not isinstance(opaque, dict) or not isinstance(opaque.get("reasoning_content"), str):
                    raise ProtocolFailure("Protocol Metadata envelope 结构无效。")
                payload["reasoning_content"] = opaque["reasoning_content"]
        elif message.role == "tool":
            payload["tool_call_id"] = message.tool_request_id
        return payload

    def _http_failure(self, status: int, body: str) -> ModelFailure:
        safe = scrub(body, (self.settings.api_key,))
        lowered = safe.casefold()
        if status in {401, 403}:
            return AuthenticationFailure("模型服务认证失败。")
        if any(
            marker in lowered
            for marker in (
                "context_length_exceeded",
                "maximum context length",
                "context window",
                "too many tokens",
            )
        ):
            return ContextWindowFailure(f"模型上下文窗口超限：HTTP {status} {safe}")
        if "thinking" in lowered or "reasoning_effort" in lowered:
            return UnsupportedThinkingFailure("模型服务不支持当前 Thinking 参数。")
        return ProtocolFailure(f"模型服务返回 HTTP {status}：{safe}")


def _optional_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _cache_hit(usage: dict[str, Any]) -> int | None:
    direct = _optional_int(usage.get("prompt_cache_hit_tokens"))
    if direct is not None:
        return direct
    details = usage.get("prompt_tokens_details")
    return _optional_int(details.get("cached_tokens")) if isinstance(details, dict) else None
