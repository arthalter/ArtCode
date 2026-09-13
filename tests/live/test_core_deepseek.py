from __future__ import annotations

import pytest

from artcode._model import DeepSeekModel
from artcode.core.model import ModelFailure, ModelMessage, ModelRequest, ModelSettings, TextDelta
from tests.live.conftest import load_live_settings


pytestmark = pytest.mark.live


async def test_real_model_interface_returns_visible_text() -> None:
    config = load_live_settings()
    model = DeepSeekModel(
        ModelSettings(
            model=config.model,
            base_url=config.base_url,
            api_key=config.api_key,
            thinking_enabled=config.thinking_enabled,
            connect_timeout_seconds=30,
            read_timeout_seconds=300,
        )
    )
    try:
        try:
            parts = [
                event.text
                async for event in model.stream(ModelRequest((ModelMessage("user", "只回复 OK"),)))
                if isinstance(event, TextDelta)
            ]
        except ModelFailure as exc:
            pytest.skip(f"environment blocked: real provider returned {exc.category}: {exc}")
    finally:
        await model.close()
    assert "".join(parts).strip()
