from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from artcode.config import ArtCodeConfig, parse_config
from artcode.errors import ConfigError


def load_live_config() -> ArtCodeConfig:
    candidates = (Path.home() / ".artcode" / "config.yml", Path(__file__).resolve().parents[2] / "artcode.yaml")
    source = next((path for path in candidates if path.exists()), None)
    if source is None:
        pytest.skip("environment blocked: no local DeepSeek configuration")
    try:
        raw = yaml.safe_load(source.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and isinstance(raw.get("thinking"), dict):
            raw["thinking"] = {key: value for key, value in raw["thinking"].items() if key != "effort"}
        raw["model"] = "deepseek-v4-flash"
        config = parse_config(raw)
    except (OSError, yaml.YAMLError, ConfigError) as exc:
        pytest.skip(f"environment blocked: invalid local DeepSeek configuration ({type(exc).__name__})")
    if "your-deepseek-api-key" in config.api_key or config.api_key.startswith("<"):
        pytest.skip("environment blocked: placeholder DeepSeek API key")
    return config
