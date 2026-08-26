from __future__ import annotations

from pathlib import Path

import pytest

from artcode.config import ArtCodeConfig, load_config
from artcode.errors import ConfigError


def load_live_config() -> ArtCodeConfig:
    candidates = (Path.home() / ".artcode" / "config.yml", Path(__file__).resolve().parents[2] / "artcode.yaml")
    source = next((path for path in candidates if path.exists()), None)
    if source is None:
        pytest.skip("environment blocked: no local model configuration")
    try:
        config = load_config(source)
    except (OSError, ConfigError) as exc:
        pytest.skip(f"environment blocked: invalid local model configuration ({type(exc).__name__})")
    if config.api_key.startswith(("your-", "<")):
        pytest.skip("environment blocked: placeholder API key")
    return config

def make_live_provider():
    """A live provider with generous timeouts for slow thinking models.

    Real tool-using tasks can take minutes; the interactive 60 s read
    timeout is not appropriate for automated acceptance runs.
    """
    import httpx

    from artcode.providers import DeepSeekChatProvider

    config = load_live_config()
    client = httpx.AsyncClient(
        timeout=httpx.Timeout(
            None, connect=30.0, read=300.0, write=30.0, pool=30.0
        )
    )
    return DeepSeekChatProvider(config, client=client), client
