from __future__ import annotations

import pytest

from pathlib import Path

from artcode.config import ArtCodeConfig, ContextConfig, load_config, parse_config
from artcode.errors import ConfigError
from artcode.runtime.state import StartupStatusSnapshot


def valid_raw(allowed_dir: Path | None = None) -> dict:
    raw = {
        "protocol": "openai",
        "model": "test-model",
        "base_url": "https://api.example.test/v1",
        "api_key": "sk-test-secret-value",
        "thinking": {"enabled": True},
    }
    if allowed_dir is not None:
        raw["tools"] = {"allowed_dirs": [str(allowed_dir)]}
    return raw


def raw_without_tools() -> dict:
    return {
        "protocol": "openai",
        "model": "test-model",
        "base_url": "https://api.example.test/v1",
        "api_key": "sk-test-secret-value",
        "thinking": {"enabled": True},
    }


def test_parse_valid_config() -> None:
    config = parse_config(valid_raw())

    assert isinstance(config, ArtCodeConfig)
    assert config.protocol == "openai"
    assert config.thinking.enabled is True


def test_load_missing_file(tmp_path) -> None:
    with pytest.raises(ConfigError, match="找不到配置文件"):
        load_config(tmp_path / "artcode.yaml")


def test_load_invalid_yaml(tmp_path) -> None:
    path = tmp_path / "artcode.yaml"
    path.write_text("protocol: [\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="不是合法 YAML"):
        load_config(path)


def test_top_level_must_be_map() -> None:
    with pytest.raises(ConfigError, match="顶层必须是对象"):
        parse_config(["not", "a", "map"])


@pytest.mark.parametrize("field", ["protocol", "model", "base_url", "api_key"])
def test_missing_required_fields(field: str) -> None:
    raw = valid_raw()
    raw.pop(field)

    with pytest.raises(ConfigError, match=f"配置缺少字段：{field}"):
        parse_config(raw)


def test_missing_model_is_rejected() -> None:
    raw = valid_raw()
    raw.pop("model")

    with pytest.raises(ConfigError, match="配置缺少字段：model"):
        parse_config(raw)


@pytest.mark.parametrize("field", ["model", "base_url", "api_key"])
def test_empty_required_string_fields(field: str) -> None:
    raw = valid_raw()
    raw[field] = "   "

    with pytest.raises(ConfigError, match=f"配置字段 {field} 不能为空"):
        parse_config(raw)


def test_unsupported_protocol() -> None:
    raw = valid_raw()
    raw["protocol"] = "anthropic"

    with pytest.raises(ConfigError, match="当前不支持"):
        parse_config(raw)


def test_thinking_is_optional_and_defaults_to_off() -> None:
    raw = valid_raw()
    raw.pop("thinking")

    config = parse_config(raw)

    assert config.thinking.enabled is False


def test_thinking_enabled_must_be_bool() -> None:
    raw = valid_raw()
    raw["thinking"]["enabled"] = "true"

    with pytest.raises(ConfigError, match="thinking.enabled 必须是布尔值"):
        parse_config(raw)


def test_thinking_effort_must_be_allowed_value() -> None:
    raw = valid_raw()
    raw["thinking"]["effort"] = "max"

    with pytest.raises(ConfigError, match="thinking.*未知字段.*effort"):
        parse_config(raw)


def test_safe_status_masks_api_key() -> None:
    config = parse_config(valid_raw())
    status = StartupStatusSnapshot.from_config(config)

    assert status.api_key_configured is True
    assert config.api_key not in repr(status)


def test_startup_status_has_no_chapter_product_text() -> None:
    status = StartupStatusSnapshot.from_config(parse_config(valid_raw()))

    assert "chapter" not in status.__dataclass_fields__


def test_context_defaults_and_thresholds() -> None:
    config = parse_config(valid_raw())

    assert config.context == ContextConfig(1_000_000)
    assert config.context.automatic_threshold == 835_000
    assert config.context.forced_threshold == 885_000
    assert StartupStatusSnapshot.from_config(config).context_window_tokens == 1_000_000


@pytest.mark.parametrize("value", [200_000, 500_000, 1_000_000])
def test_context_window_accepts_supported_range(value: int) -> None:
    raw = valid_raw()
    raw["context"] = {"window_tokens": value}

    assert parse_config(raw).context.window_tokens == value


@pytest.mark.parametrize("value", [199_999, 1_000_001, True, "200000", 200000.0])
def test_context_window_rejects_invalid_values(value) -> None:
    raw = valid_raw()
    raw["context"] = {"window_tokens": value}

    with pytest.raises(ConfigError, match="context.window_tokens"):
        parse_config(raw)


def test_old_tools_allowed_dirs_is_rejected() -> None:
    raw = valid_raw()
    raw["tools"] = {"allowed_dirs": ["relative/path"]}

    with pytest.raises(ConfigError, match="未知字段：tools"):
        parse_config(raw)


def test_default_config_path_is_artcode_home(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    with pytest.raises(ConfigError, match=r"\.artcode/config.yml"):
        load_config()
