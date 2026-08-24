from __future__ import annotations

import pytest

pytestmark = pytest.mark.live

from artcode.config import ArtCodeConfig
from tests.live.conftest import load_live_config
from artcode.prompting import build_system_prompt
from artcode.providers import DeepSeekChatProvider, ProviderRequest
from artcode.providers.events import UsageReported


def required_live_config() -> ArtCodeConfig:
    return load_live_config()


async def collect_cached_tokens(provider: DeepSeekChatProvider, messages: list[dict[str, str]]) -> int:
    cached_tokens = 0
    usage_events = 0
    async for event in provider.stream(ProviderRequest.from_parts(messages)):
        if isinstance(event, UsageReported):
            usage_events += 1
            value = event.usage.cached_tokens
            if isinstance(value, int):
                cached_tokens = max(cached_tokens, value)
    if usage_events == 0:
        pytest.fail("real API did not return streaming usage; check stream_options.include_usage support")
    return cached_tokens


async def test_live_prompt_cache_usage_is_reported_without_requiring_provider_cache_hits() -> None:
    provider = DeepSeekChatProvider(required_live_config())
    stable_block = "\n".join(
        [
            build_system_prompt(),
            "稳定缓存验证片段：",
            *[f"cache-line-{index}: ArtCode keeps stable prompt prefixes for cache validation." for index in range(300)],
        ]
    )
    messages = [
        {"role": "system", "content": stable_block},
        {"role": "user", "content": "只回复 OK。"},
    ]

    observations = [await collect_cached_tokens(provider, messages) for _ in range(3)]

    assert all(value >= 0 for value in observations)
