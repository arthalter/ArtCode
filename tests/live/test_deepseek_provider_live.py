from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from artcode.config import ThinkingConfig
from artcode.providers.base import ProviderRequest
from artcode.providers.deepseek import DeepSeekChatProvider
from artcode.providers.events import ContentDelta, ReasoningDelta, StreamCompleted, UsageReported
from tests.live.conftest import load_live_config

pytestmark = [pytest.mark.ch10_5, pytest.mark.live]


async def collect(provider, request):
    return [event async for event in provider.stream(request)]


async def test_live_thinking_off_returns_text_and_usage() -> None:
    provider = DeepSeekChatProvider(replace(load_live_config(), thinking=ThinkingConfig(False)))
    try:
        events = await collect(provider, ProviderRequest.from_parts([{"role": "user", "content": "只回复 7"}]))
    finally:
        await provider.close()
    assert any(isinstance(event, ContentDelta) for event in events)
    assert any(isinstance(event, UsageReported) for event in events)


async def test_live_thinking_high_returns_reasoning_and_text() -> None:
    provider = DeepSeekChatProvider(replace(load_live_config(), thinking=ThinkingConfig(True)))
    try:
        events = await collect(provider, ProviderRequest.from_parts([{"role": "user", "content": "计算 17*19，只给最终数字"}]))
    finally:
        await provider.close()
    assert any(isinstance(event, ReasoningDelta) for event in events)
    assert any(isinstance(event, ContentDelta) for event in events)


async def test_live_usage_contains_positive_total() -> None:
    provider = DeepSeekChatProvider(load_live_config())
    try:
        events = await collect(provider, ProviderRequest.from_parts([{"role": "user", "content": "回复 OK"}]))
    finally:
        await provider.close()
    usages = [event.usage for event in events if isinstance(event, UsageReported)]
    assert usages and (usages[-1].total_tokens or 0) > 0


async def test_live_small_output_limit_preserves_finish_reason() -> None:
    provider = DeepSeekChatProvider(load_live_config())
    try:
        events = await collect(
            provider,
            ProviderRequest.from_parts(
                [{"role": "user", "content": "写一段至少 200 字的说明"}],
                max_output_tokens=1,
                thinking_enabled=False,
            ),
        )
    finally:
        await provider.close()
    completed = next(event for event in events if isinstance(event, StreamCompleted))
    assert completed.finish_reason in {"length", "stop"}


async def test_live_stream_can_be_cancelled_and_client_closed() -> None:
    provider = DeepSeekChatProvider(load_live_config())

    async def consume() -> None:
        async for _ in provider.stream(
            ProviderRequest.from_parts([{"role": "user", "content": "连续输出很长的自然数序列"}])
        ):
            await asyncio.sleep(0)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await provider.close()
    assert provider._client.is_closed is True
