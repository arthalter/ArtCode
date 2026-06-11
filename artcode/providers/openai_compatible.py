from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator, Sequence
from typing import Any

import httpx

from artcode.config import ArtCodeConfig
from artcode.errors import (
    AuthenticationError,
    ModelError,
    NetworkError,
    StreamInterruptedError,
    ThinkingModeUnsupportedError,
    TimeoutError,
    scrub_secrets,
)

from .events import content_delta_event, done_event, tool_calls_event
from .sse import SSEDecoder
from .tool_calls import ToolCallAccumulator


CONNECT_TIMEOUT_SECONDS = 10.0
READ_TIMEOUT_SECONDS = 60.0


class OpenAICompatibleProvider:
    def __init__(self, config: ArtCodeConfig, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.config = config
        self._transport = transport

    async def stream_chat(
        self,
        messages: Sequence[dict[str, Any]],
        tools: Sequence[dict[str, Any]] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        payload = build_request_payload(self.config, messages, tools)
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }

        try:
            async with httpx.AsyncClient(
                timeout=provider_timeout(),
                transport=self._transport,
            ) as client:
                async with client.stream(
                    "POST",
                    chat_completions_url(self.config.base_url),
                    headers=headers,
                    json=payload,
                ) as response:
                    if response.status_code >= 400:
                        body = (await response.aread()).decode("utf-8", errors="replace")
                        raise map_http_error(response.status_code, body, [self.config.api_key])

                    async for event in self._iter_stream_events(response):
                        yield event
        except httpx.TimeoutException as exc:
            raise TimeoutError(
                "请求 DeepSeek 超时。",
                f"连接超时为 {int(CONNECT_TIMEOUT_SECONDS)} 秒，读取超时为 {int(READ_TIMEOUT_SECONDS)} 秒；请检查网络或稍后重试。",
            ) from exc
        except (httpx.ConnectError, httpx.NetworkError) as exc:
            raise NetworkError("无法连接 DeepSeek API。", "请检查网络、代理或 base_url。") from exc
        except (httpx.RemoteProtocolError, httpx.ReadError, httpx.DecodingError) as exc:
            raise StreamInterruptedError("流式响应中途断开。", "本轮回复没有写入上下文，请稍后重试。") from exc

    async def _iter_stream_events(self, response: httpx.Response) -> AsyncIterator[dict[str, Any]]:
        decoder = SSEDecoder()
        tool_calls = ToolCallAccumulator()
        seen_done = False

        async for line in response.aiter_lines():
            for sse_event in decoder.feed(line):
                if sse_event.done:
                    seen_done = True
                    if tool_calls.has_calls():
                        yield tool_calls_event(tool_calls.finish())
                    yield done_event()
                    return
                for event in _events_from_sse_data(sse_event.data, tool_calls):
                    yield event

        for sse_event in decoder.close():
            if sse_event.done:
                seen_done = True
                if tool_calls.has_calls():
                    yield tool_calls_event(tool_calls.finish())
                yield done_event()
                return
            for event in _events_from_sse_data(sse_event.data, tool_calls):
                yield event

        if not seen_done:
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


def build_request_payload(
    config: ArtCodeConfig,
    messages: Sequence[dict[str, Any]],
    tools: Sequence[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": config.model,
        "messages": list(messages),
        "stream": True,
    }
    if tools is not None:
        payload["tools"] = list(tools)
        payload["tool_choice"] = "auto"
    if config.thinking.enabled:
        payload["thinking"] = {"type": "enabled"}
        payload["reasoning_effort"] = map_reasoning_effort(config.thinking.effort)
    return payload


def map_reasoning_effort(effort: str) -> str:
    if effort in {"low", "medium"}:
        return "high"
    return "high"


def map_http_error(status_code: int, response_body: str, secrets: Sequence[str]) -> Exception:
    safe_body = scrub_secrets(response_body, secrets)
    if status_code in {401, 403}:
        return AuthenticationError("DeepSeek 认证失败。", "请检查 artcode.yaml 中的 api_key 是否正确。")
    if _looks_like_thinking_error(safe_body):
        return ThinkingModeUnsupportedError(
            "DeepSeek 当前不接受 Thinking Mode 参数。",
            "请尝试关闭 thinking.enabled，或确认当前模型是否支持 Thinking Mode。",
        )
    if status_code in {400, 404, 422}:
        return ModelError("DeepSeek 请求或模型配置不可用。", f"服务端返回 HTTP {status_code}：{safe_body}")
    return ModelError("DeepSeek API 返回错误。", f"HTTP {status_code}：{safe_body}")


def _events_from_sse_data(data: str, tool_calls: ToolCallAccumulator) -> Iterator[dict[str, Any]]:
    try:
        payload = json.loads(data)
    except json.JSONDecodeError as exc:
        raise StreamInterruptedError("流式响应格式无法解析。", "DeepSeek 返回了非 JSON 的 SSE data。") from exc

    choices = payload.get("choices")
    if not isinstance(choices, list):
        raise StreamInterruptedError("流式响应结构异常。", "SSE data 中缺少 choices。")

    for choice in choices:
        if not isinstance(choice, dict):
            continue
        delta = choice.get("delta") or {}
        if not isinstance(delta, dict):
            continue
        content = delta.get("content")
        if isinstance(content, str) and content:
            yield content_delta_event(content)
        delta_tool_calls = delta.get("tool_calls")
        if isinstance(delta_tool_calls, list):
            tool_calls.add_delta(delta_tool_calls)


def _looks_like_thinking_error(response_body: str) -> bool:
    lowered = response_body.lower()
    return "thinking" in lowered or "reasoning_effort" in lowered or "reasoning effort" in lowered
