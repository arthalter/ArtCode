from __future__ import annotations

from hypothesis import given, strategies as st
import pytest

from artcode.config import parse_config
from artcode.errors import ConfigError

pytestmark = [pytest.mark.ch10_5, pytest.mark.property]


def base() -> dict:
    return {"protocol": "openai", "base_url": "https://api.deepseek.com", "api_key": "secret"}


unknown_keys = st.sets(
    st.text(alphabet=st.characters(categories=("Ll", "Lu")), min_size=1, max_size=8)
    .filter(lambda value: value not in {"protocol", "model", "base_url", "api_key", "thinking", "context", "mcp_servers"}),
    min_size=1,
    max_size=8,
)
thinking_unknown_keys = unknown_keys.filter(lambda keys: "enabled" not in keys)
context_unknown_keys = unknown_keys.filter(lambda keys: "window_tokens" not in keys)


@given(unknown_keys)
def test_all_top_level_unknown_keys_are_reported(keys: set[str]) -> None:
    raw = base()
    raw.update(dict.fromkeys(keys, 1))
    with pytest.raises(ConfigError) as captured:
        parse_config(raw)
    assert all(key in captured.value.user_message for key in keys)


@given(thinking_unknown_keys)
def test_all_thinking_unknown_keys_are_reported(keys: set[str]) -> None:
    raw = base()
    raw["thinking"] = {"enabled": True, **dict.fromkeys(keys, 1)}
    with pytest.raises(ConfigError) as captured:
        parse_config(raw)
    assert all(key in captured.value.user_message for key in keys)


@given(context_unknown_keys)
def test_all_context_unknown_keys_are_reported(keys: set[str]) -> None:
    raw = base()
    raw["context"] = {"window_tokens": 500_000, **dict.fromkeys(keys, 1)}
    with pytest.raises(ConfigError) as captured:
        parse_config(raw)
    assert all(key in captured.value.user_message for key in keys)


@given(st.integers(min_value=200_000, max_value=1_000_000))
def test_legal_windows_preserve_exact_value_and_ratio(value: int) -> None:
    raw = base()
    raw["context"] = {"window_tokens": value}
    context = parse_config(raw).context
    assert context.window_tokens == value
    assert context.automatic_threshold == value * 167 // 200
    assert context.forced_threshold == value * 177 // 200


@given(st.integers(max_value=199_999))
def test_every_below_minimum_integer_is_rejected(value: int) -> None:
    raw = base()
    raw["context"] = {"window_tokens": value}
    with pytest.raises(ConfigError):
        parse_config(raw)


@given(st.integers(min_value=1_000_001))
def test_every_above_maximum_integer_is_rejected(value: int) -> None:
    raw = base()
    raw["context"] = {"window_tokens": value}
    with pytest.raises(ConfigError):
        parse_config(raw)


@given(st.sampled_from([None, True, False, [], "", 1, 1.0]))
def test_every_sampled_non_mapping_mcp_container_is_rejected(value) -> None:
    raw = base()
    raw["mcp_servers"] = value
    with pytest.raises(ConfigError):
        parse_config(raw)


@given(st.dictionaries(st.text(min_size=1, max_size=12), st.dictionaries(st.text(min_size=1), st.text(), max_size=3), max_size=8))
def test_mcp_mapping_copy_is_stable(servers: dict) -> None:
    raw = base()
    raw["mcp_servers"] = servers
    config = parse_config(raw)
    assert dict(config.mcp_servers_raw) == servers
