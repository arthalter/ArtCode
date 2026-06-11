from __future__ import annotations

import pytest

from pathlib import Path

from artcode.config import ArtCodeConfig, DEFAULT_ALLOWED_DIR, load_config, parse_config
from artcode.errors import ConfigError


def valid_raw(allowed_dir: Path | None = None) -> dict:
    raw = {
        "protocol": "openai",
        "model": "deepseek-v4-flash",
        "base_url": "https://api.deepseek.com",
        "api_key": "sk-test-secret-value",
        "thinking": {"enabled": True, "effort": "high"},
    }
    if allowed_dir is not None:
        raw["tools"] = {"allowed_dirs": [str(allowed_dir)]}
    return raw


def raw_without_tools() -> dict:
    return {
        "protocol": "openai",
        "model": "deepseek-v4-flash",
        "base_url": "https://api.deepseek.com",
        "api_key": "sk-test-secret-value",
        "thinking": {"enabled": True, "effort": "high"},
    }


def test_parse_valid_config() -> None:
    config = parse_config(valid_raw())

    assert isinstance(config, ArtCodeConfig)
    assert config.protocol == "openai"
    assert config.thinking.enabled is True
    assert config.thinking.effort == "high"
    assert config.tools.allowed_dirs


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
    assert config.thinking.effort == "high"


def test_thinking_enabled_must_be_bool() -> None:
    raw = valid_raw()
    raw["thinking"]["enabled"] = "true"

    with pytest.raises(ConfigError, match="thinking.enabled 必须是布尔值"):
        parse_config(raw)


def test_thinking_effort_must_be_allowed_value() -> None:
    raw = valid_raw()
    raw["thinking"]["effort"] = "max"

    with pytest.raises(ConfigError, match="thinking.effort"):
        parse_config(raw)


def test_safe_status_masks_api_key() -> None:
    config = parse_config(valid_raw())
    status = config.safe_status()

    assert status.masked_api_key != config.api_key
    assert config.api_key not in status.masked_api_key


def test_chapter_name_is_ch03() -> None:
    status = parse_config(valid_raw()).safe_status()

    assert status.chapter == "ch03：工具系统"


def test_tools_default_to_experiment_dir() -> None:
    config = parse_config(raw_without_tools())

    assert config.tools.allowed_dirs == (DEFAULT_ALLOWED_DIR.resolve(),)


def test_tools_allowed_dirs_are_absolute_and_created(tmp_path) -> None:
    allowed_dir = tmp_path / "sandbox"

    config = parse_config(valid_raw(allowed_dir))

    assert config.tools.allowed_dirs == (allowed_dir.resolve(),)
    assert allowed_dir.exists()


def test_tools_allowed_dirs_must_be_absolute() -> None:
    raw = valid_raw()
    raw["tools"] = {"allowed_dirs": ["relative/path"]}

    with pytest.raises(ConfigError, match="只支持绝对路径"):
        parse_config(raw)


def test_tools_allowed_dirs_must_not_contain_empty_path() -> None:
    raw = valid_raw()
    raw["tools"] = {"allowed_dirs": ["   "]}

    with pytest.raises(ConfigError, match="不能包含空路径"):
        parse_config(raw)


def test_tools_allowed_dirs_items_must_be_strings() -> None:
    raw = valid_raw()
    raw["tools"] = {"allowed_dirs": [123]}

    with pytest.raises(ConfigError, match="每一项都必须是绝对路径字符串"):
        parse_config(raw)


def test_safe_status_contains_allowed_dirs(tmp_path) -> None:
    allowed_dir = tmp_path / "sandbox"
    status = parse_config(valid_raw(allowed_dir)).safe_status()

    assert status.allowed_dirs == (str(allowed_dir.resolve()),)
