from __future__ import annotations

from pathlib import Path

import pytest

from artcode.config import ArtCodeConfig, ConfigError, load_config
from artcode.prompting import build_system_prompt
from artcode.providers.events import TOKEN_USAGE
from artcode.providers.openai_compatible import OpenAICompatibleProvider


ROOT = Path(__file__).resolve().parents[2]


def required_live_config() -> ArtCodeConfig:
    try:
        config = load_config(ROOT / "artcode.yaml")
    except ConfigError as exc:
        pytest.fail(f"ch05 cache validation requires real API config: {exc.message}")
    if "your-deepseek-api-key" in config.api_key or config.api_key.startswith("<"):
        pytest.fail("ch05 cache validation requires a real API key in artcode.yaml")
    return config


async def collect_cached_tokens(provider: OpenAICompatibleProvider, messages: list[dict[str, str]]) -> int:
    cached_tokens = 0
    usage_events = 0
    async for event in provider.stream_chat(messages):
        if event["type"] == TOKEN_USAGE:
            usage_events += 1
            value = event.get("cached_tokens")
            if isinstance(value, int):
                cached_tokens = max(cached_tokens, value)
    if usage_events == 0:
        pytest.fail("real API did not return streaming usage; check stream_options.include_usage support")
    return cached_tokens


async def test_live_prompt_cache_hit_tokens_are_positive() -> None:
    provider = OpenAICompatibleProvider(required_live_config())
    stable_block = "\n".join(
        [
            build_system_prompt(),
            "稳定缓存验证片段：",
            *[f"cache-line-{index}: ArtCode ch05 keeps stable prompt prefixes for cache validation." for index in range(300)],
        ]
    )
    messages = [
        {"role": "system", "content": stable_block},
        {"role": "user", "content": "只回复 OK。"},
    ]

    observations = [await collect_cached_tokens(provider, messages) for _ in range(3)]

    assert max(observations) > 0, f"expected real prompt cache hit > 0, observed cached_tokens={observations}"
