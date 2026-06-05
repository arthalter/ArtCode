from __future__ import annotations

import pytest

from artcode.config import ArtCodeConfig, ThinkingConfig
from artcode.errors import AuthenticationError, ModelError, ThinkingModeUnsupportedError
from artcode.providers.openai_compatible import (
    CONNECT_TIMEOUT_SECONDS,
    READ_TIMEOUT_SECONDS,
    build_request_payload,
    chat_completions_url,
    map_http_error,
    provider_timeout,
)


def config(thinking_enabled: bool = False, effort: str = "high") -> ArtCodeConfig:
    return ArtCodeConfig(
        protocol="openai",
        model="deepseek-v4-flash",
        base_url="https://api.deepseek.com/",
        api_key="sk-secret-key",
        thinking=ThinkingConfig(enabled=thinking_enabled, effort=effort),
    )


def test_chat_completions_url_does_not_double_slash() -> None:
    assert chat_completions_url("https://api.deepseek.com/") == "https://api.deepseek.com/chat/completions"


def test_payload_without_thinking_omits_thinking_fields() -> None:
    payload = build_request_payload(config(False), [{"role": "user", "content": "hi"}])

    assert payload["stream"] is True
    assert "thinking" not in payload
    assert "reasoning_effort" not in payload


def test_payload_with_thinking_maps_effort() -> None:
    payload = build_request_payload(config(True, "low"), [{"role": "user", "content": "hi"}])

    assert payload["thinking"] == {"type": "enabled"}
    assert payload["reasoning_effort"] == "high"


def test_provider_timeout_values() -> None:
    timeout = provider_timeout()

    assert timeout.connect == CONNECT_TIMEOUT_SECONDS
    assert timeout.read == READ_TIMEOUT_SECONDS


def test_http_errors_are_mapped_without_leaking_secret() -> None:
    error = map_http_error(400, "bad sk-secret-key", ["sk-secret-key"])

    assert isinstance(error, ModelError)
    assert "sk-secret-key" not in error.user_message


@pytest.mark.parametrize("status_code", [401, 403])
def test_auth_errors_are_mapped(status_code: int) -> None:
    assert isinstance(map_http_error(status_code, "unauthorized", []), AuthenticationError)


def test_thinking_errors_are_mapped() -> None:
    error = map_http_error(400, "unsupported reasoning_effort", [])

    assert isinstance(error, ThinkingModeUnsupportedError)
