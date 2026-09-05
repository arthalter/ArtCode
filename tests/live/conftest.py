from __future__ import annotations

from pathlib import Path

import pytest

from artcode._application.config import ConfigurationFailure, load_config
from artcode.core.model import ModelSettings


def load_live_settings() -> ModelSettings:
    candidates = (
        Path.home() / ".artcode" / "config.yml",
        Path(__file__).resolve().parents[2] / "artcode.yaml",
    )
    source = next((path for path in candidates if path.exists()), None)
    if source is None:
        pytest.skip("environment blocked: no local model configuration")
    try:
        config = load_config(source, Path("/dev/null/artcode-project-config"))
    except (OSError, ConfigurationFailure) as exc:
        pytest.skip(f"environment blocked: invalid local model configuration ({type(exc).__name__})")
    if config.model.api_key.startswith(("your-", "<")):
        pytest.skip("environment blocked: placeholder API key")
    return config.model
