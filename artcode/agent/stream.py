from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any, Callable

from artcode.errors import StreamInterruptedError
from artcode.providers.base import ProviderRequest, StreamingProvider, stream_provider
from artcode.providers.events import (
    ContentDelta,
    ReasoningDelta,
    StreamCompleted,
    ToolCallsCompleted,
    UsageReported,
)
from artcode.providers.tool_calls import ToolCall

from .events import AgentEvent, ModelTurn, TokenUsage, text_delta_event, token_usage_event


class StreamCollector:
    async def collect(
        self,
        provider: StreamingProvider,
        messages: Sequence[dict[str, Any]],
        tools: Sequence[dict[str, Any]] | None,
        *,
        on_dispatch: Callable[[], None] | None = None,
    ) -> AsyncIterator[AgentEvent | ModelTurn]:
        parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_calls: tuple[ToolCall, ...] = ()
        usage: TokenUsage | None = None
        request = ProviderRequest.from_parts(messages, tools)
        if on_dispatch is not None:
            on_dispatch()

        async for event in stream_provider(provider, request):
            if isinstance(event, ContentDelta):
                parts.append(event.text)
                yield text_delta_event(event.text)
            elif isinstance(event, ReasoningDelta):
                reasoning_parts.append(event.text)
            elif isinstance(event, ToolCallsCompleted):
                tool_calls = event.tool_calls
            elif isinstance(event, UsageReported):
                usage = event.usage
                yield token_usage_event(usage)
            elif isinstance(event, StreamCompleted):
                yield ModelTurn(
                    text="".join(parts),
                    reasoning_content="".join(reasoning_parts),
                    tool_calls=tool_calls,
                    usage=usage,
                    finish_reason=event.finish_reason,
                )
                return
            else:
                raise TypeError(f"unsupported provider event: {type(event).__name__}")

        raise StreamInterruptedError("流式响应意外结束。", "Provider 未产生 StreamCompleted 事件。")
