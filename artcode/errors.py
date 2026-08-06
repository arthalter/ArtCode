from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


def mask_secret(secret: str) -> str:
    value = str(secret)
    if not value:
        return "<empty>"
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def scrub_secrets(text: str, secrets: Iterable[str] = ()) -> str:
    scrubbed = str(text)
    for secret in secrets:
        if secret:
            scrubbed = scrubbed.replace(secret, mask_secret(secret))
    return scrubbed


@dataclass
class ArtCodeError(Exception):
    message: str
    hint: str | None = None

    @property
    def user_message(self) -> str:
        if self.hint:
            return f"{self.message}\n提示：{self.hint}"
        return self.message

    def __str__(self) -> str:
        return self.user_message


class ConfigError(ArtCodeError):
    pass


class RequestError(ArtCodeError):
    pass


class AuthenticationError(RequestError):
    pass


class NetworkError(RequestError):
    pass


class ModelError(RequestError):
    pass


class ContextWindowExceededError(RequestError):
    pass


class TimeoutError(RequestError):
    pass


class ThinkingModeUnsupportedError(RequestError):
    pass


class StreamInterruptedError(RequestError):
    pass
