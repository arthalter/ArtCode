from __future__ import annotations

from copy import deepcopy

import pytest

from artcode.config import parse_config
from artcode.errors import ConfigError
from artcode.runtime.state import StartupStatusSnapshot

pytestmark = pytest.mark.ch10_5


def valid_raw() -> dict:
    return {
        "protocol": "openai",
        "model": "test-model",
        "base_url": "https://api.example.test/v1",
        "api_key": "sk-probe-secret",
    }


@pytest.mark.parametrize(
    ("unknown", "ordered"),
    [
        (("zeta", "alpha"), "alpha、zeta"),
        (("tools", "workspace"), "tools、workspace"),
        (("permission", "sandbox"), "permission、sandbox"),
        (("memory", "provider"), "memory、provider"),
        (("chapter", "safe_status"), "chapter、safe_status"),
        (("a", "b", "c"), "a、b、c"),
        (("model_id", "token_limit"), "model_id、token_limit"),
        (("unknown_中文", "unknown_ascii"), "unknown_ascii、unknown_中文"),
    ],
    ids=("sorted", "legacy-tools", "runtime", "services", "chapter", "three", "aliases", "unicode"),
)
def test_top_level_reports_every_unknown_key(unknown: tuple[str, ...], ordered: str) -> None:
    raw = valid_raw()
    raw.update(dict.fromkeys(unknown, True))
    with pytest.raises(ConfigError, match=ordered):
        parse_config(raw)


@pytest.mark.parametrize("value", [None, [], "server", 1, True])
def test_mcp_container_rejects_every_non_mapping_shape(value) -> None:
    raw = valid_raw()
    raw["mcp_servers"] = value
    with pytest.raises(ConfigError, match="mcp_servers 必须是对象/map"):
        parse_config(raw)


@pytest.mark.parametrize(
    "value",
    [True, False, 199_999, 1_000_001, -1, 0, 199_000, 1_000_100, "1000000", 1_000_000.0],
    ids=("true", "false", "below", "above", "negative", "zero", "far-below", "far-above", "string", "float"),
)
def test_context_window_rejects_invalid_type_or_range(value) -> None:
    raw = valid_raw()
    raw["context"] = {"window_tokens": value}
    with pytest.raises(ConfigError, match="context.window_tokens"):
        parse_config(raw)


@pytest.mark.parametrize(
    "thinking",
    [
        [],
        "enabled",
        1,
        {"enabled": "true"},
        {"enabled": 1},
        {"effort": "low"},
        {"effort": "medium", "level": "high"},
    ],
    ids=("list", "string", "number", "bool-string", "bool-int", "old-effort", "two-unknown"),
)
def test_thinking_rejects_invalid_or_legacy_shapes(thinking) -> None:
    raw = valid_raw()
    raw["thinking"] = thinking
    with pytest.raises(ConfigError, match="thinking"):
        parse_config(raw)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("protocol", None),
        ("protocol", 1),
        ("protocol", ""),
        ("protocol", "anthropic"),
        ("base_url", None),
        ("base_url", []),
        ("base_url", ""),
        ("base_url", "   "),
        ("api_key", None),
        ("api_key", {}),
        ("api_key", ""),
        ("api_key", "   "),
    ],
    ids=(
        "protocol-none", "protocol-int", "protocol-empty", "protocol-unsupported",
        "url-none", "url-list", "url-empty", "url-space",
        "key-none", "key-map", "key-empty", "key-space",
    ),
)
def test_required_scalars_fail_closed(field: str, value) -> None:
    raw = valid_raw()
    raw[field] = value
    with pytest.raises(ConfigError):
        parse_config(raw)


def test_model_is_required() -> None:
    raw = valid_raw()
    raw.pop("model")
    with pytest.raises(ConfigError, match="配置缺少字段：model"):
        parse_config(raw)


def test_minimum_window_thresholds_are_proportional() -> None:
    raw = valid_raw()
    raw["context"] = {"window_tokens": 200_000}
    context = parse_config(raw).context
    assert (context.automatic_threshold, context.forced_threshold) == (167_000, 177_000)


def test_status_snapshot_has_no_secret_value() -> None:
    config = parse_config(valid_raw())
    snapshot = StartupStatusSnapshot.from_config(config)
    assert snapshot.api_key_configured is True
    assert config.api_key not in repr(snapshot)


def test_mcp_mapping_is_copied_and_read_only() -> None:
    raw = valid_raw()
    raw["mcp_servers"] = {"demo": {"transport": "stdio"}}
    original = deepcopy(raw)
    config = parse_config(raw)
    raw["mcp_servers"]["later"] = {}
    assert dict(config.mcp_servers_raw) == original["mcp_servers"]
    with pytest.raises(TypeError):
        config.mcp_servers_raw["blocked"] = {}  # type: ignore[index]
