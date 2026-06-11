from __future__ import annotations

import pytest

from artcode.agent import AgentEventType, ModelTurn, StreamCollector
from artcode.errors import StreamInterruptedError
from artcode.providers.events import content_delta_event, done_event, token_usage_event, tool_calls_event
from artcode.providers.tool_calls import ToolCall


class FakeProvider:
    def __init__(self, events: list[dict] | None = None, error: Exception | None = None) -> None:
        self.events = events or []
        self.error = error

    async def stream_chat(self, messages, tools=None):
        if self.error is not None:
            raise self.error
        for event in self.events:
            yield event


async def collect(provider: FakeProvider):
    return [item async for item in StreamCollector().collect(provider, [], None)]


async def test_stream_collector_emits_text_and_final_turn() -> None:
    items = await collect(FakeProvider([content_delta_event("你"), content_delta_event("好"), done_event()]))

    assert [item.payload["text"] for item in items if getattr(item, "type", None) == AgentEventType.TEXT_DELTA] == [
        "你",
        "好",
    ]
    assert isinstance(items[-1], ModelTurn)
    assert items[-1].text == "你好"


async def test_stream_collector_keeps_tool_calls() -> None:
    call = ToolCall("call_1", "read_file", "{}")
    items = await collect(FakeProvider([tool_calls_event([call]), done_event()]))

    assert isinstance(items[-1], ModelTurn)
    assert items[-1].tool_calls == [call]


async def test_stream_collector_forwards_token_usage() -> None:
    items = await collect(FakeProvider([token_usage_event(1, 2, 3), done_event()]))

    assert items[0].type == AgentEventType.TOKEN_USAGE
    assert items[0].payload["total_tokens"] == 3


async def test_stream_collector_propagates_provider_errors() -> None:
    provider = FakeProvider(error=StreamInterruptedError("断开"))

    with pytest.raises(StreamInterruptedError):
        await collect(provider)
