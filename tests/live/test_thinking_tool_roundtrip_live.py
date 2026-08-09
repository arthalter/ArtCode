from __future__ import annotations

from dataclasses import replace

import pytest

from artcode.config import ThinkingConfig
from artcode.providers.base import ProviderRequest
from artcode.providers.deepseek import DeepSeekChatProvider
from artcode.providers.events import ContentDelta, ReasoningDelta, ToolCallsCompleted
from tests.live.conftest import load_live_config

pytestmark = [pytest.mark.ch10_5, pytest.mark.live]


async def test_live_thinking_tool_call_replays_reasoning_content() -> None:
    provider = DeepSeekChatProvider(replace(load_live_config(), thinking=ThinkingConfig(True)))
    tool = {
        "type": "function",
        "function": {
            "name": "get_fixed_number",
            "description": "Return the fixed number required to answer the user.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    }
    first_events = []
    try:
        async for event in provider.stream(
            ProviderRequest.from_parts(
                [{"role": "user", "content": "必须先调用 get_fixed_number，再把工具数字加 1 后回答。"}],
                [tool],
            )
        ):
            first_events.append(event)
        calls = next(event.tool_calls for event in first_events if isinstance(event, ToolCallsCompleted))
        reasoning = "".join(event.text for event in first_events if isinstance(event, ReasoningDelta))
        assert reasoning
        assistant = {
            "role": "assistant",
            "content": "",
            "reasoning_content": reasoning,
            "tool_calls": [
                {
                    "id": calls[0].id,
                    "type": "function",
                    "function": {"name": calls[0].name, "arguments": calls[0].arguments_json},
                }
            ],
        }
        messages = [
            {"role": "user", "content": "必须先调用 get_fixed_number，再把工具数字加 1 后回答。"},
            assistant,
            {"role": "tool", "tool_call_id": calls[0].id, "name": calls[0].name, "content": "41"},
        ]
        second = [event async for event in provider.stream(ProviderRequest.from_parts(messages, [tool]))]
    finally:
        await provider.close()
    assert any(isinstance(event, ContentDelta) for event in second)
