from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from artcode.providers.base import StreamingProvider
from artcode.providers.events import CONTENT_DELTA, DONE, TOKEN_USAGE, TOOL_CALLS
from artcode.providers.tool_calls import ToolCall

from .events import AgentEvent, ModelTurn, TokenUsage, text_delta_event, token_usage_event


class StreamCollector:
    async def collect(
        self,
        provider: StreamingProvider,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> AsyncIterator[AgentEvent | ModelTurn]:
        parts: list[str] = []
        tool_calls: list[ToolCall] = []
        usage: TokenUsage | None = None

        async for event in provider.stream_chat(messages, tools=tools):
            event_type = event.get("type")
            if event_type == CONTENT_DELTA:
                text = event.get("text", "")
                if isinstance(text, str):
                    parts.append(text)
                    yield text_delta_event(text)
            elif event_type == TOOL_CALLS:
                calls = event.get("tool_calls", [])
                if isinstance(calls, list):
                    tool_calls = calls
            elif event_type == TOKEN_USAGE:
                usage = TokenUsage.from_event_payload(event)
                yield token_usage_event(usage)
            elif event_type == DONE:
                yield ModelTurn("".join(parts), tool_calls, usage)
                return

        yield ModelTurn("".join(parts), tool_calls, usage)
