from __future__ import annotations

import pytest
import yaml

from artcode.config import load_config
from artcode.errors import ConfigError
from artcode.runtime.state import StartupStatusSnapshot

pytestmark = pytest.mark.ch10_5


def write_config(tmp_path, raw: dict):
    path = tmp_path / "config.yml"
    path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    return path


def minimal() -> dict:
    return {
        "protocol": "openai",
        "model": "test-model",
        "base_url": "https://api.example.test/v1",
        "api_key": "secret-value",
    }


def test_minimal_file_loads_configured_model_with_generic_window(tmp_path) -> None:
    config = load_config(write_config(tmp_path, minimal()))
    assert (config.model, config.context.window_tokens) == ("test-model", 1_000_000)


def test_file_with_two_unknown_fields_reports_both_before_provider_start(tmp_path) -> None:
    raw = minimal() | {"unknown_z": 1, "unknown_a": 2}
    with pytest.raises(ConfigError, match="unknown_a、unknown_z"):
        load_config(write_config(tmp_path, raw))


def test_null_mcp_container_fails_during_configuration(tmp_path) -> None:
    raw = minimal() | {"mcp_servers": None}
    with pytest.raises(ConfigError, match="mcp_servers"):
        load_config(write_config(tmp_path, raw))


def test_startup_snapshot_exposes_only_secret_presence(tmp_path) -> None:
    config = load_config(write_config(tmp_path, minimal()))
    snapshot = StartupStatusSnapshot.from_config(config)
    assert snapshot.api_key_configured is True
    assert "secret-value" not in repr(snapshot)


def test_smaller_window_changes_both_thresholds_in_loaded_config(tmp_path) -> None:
    raw = minimal() | {"context": {"window_tokens": 400_000}}
    context = load_config(write_config(tmp_path, raw)).context
    assert (context.automatic_threshold, context.forced_threshold) == (334_000, 354_000)
