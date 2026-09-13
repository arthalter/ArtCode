from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Iterable


_KEY_VALUE_SECRET = re.compile(
    r"(?i)(\b(?:api[_-]?key|access[_-]?token|token|secret|password)\b\s*[:=]\s*)"
    r"([^\s,;\]\[}{]+|\"[^\"]*\"|'[^']*')"
)
_AUTH_SECRET = re.compile(r"(?i)(\b(?:authorization|bearer)\b\s*[:=]?\s*)([^\s,;]+)")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


@dataclass(frozen=True)
class Preview:
    text: str
    sha256: str
    original_chars: int
    truncated: bool


class Redactor:
    def __init__(self, secrets: Iterable[str] = ()) -> None:
        self._secrets = tuple(
            sorted({item for item in secrets if item}, key=len, reverse=True)
        )

    def redact(self, value: str) -> str:
        text = value
        for secret in self._secrets:
            text = text.replace(secret, "<redacted>")
        text = _KEY_VALUE_SECRET.sub(r"\1<redacted>", text)
        return _AUTH_SECRET.sub(r"\1<redacted>", text)

    def preview(self, value: str, *, limit: int) -> Preview:
        redacted = self.redact(value)
        truncated = len(redacted) > limit
        visible = redacted[:limit]
        if truncated:
            visible += "…<truncated>"
        return Preview(
            text=visible,
            sha256=sha256_text(redacted),
            original_chars=len(redacted),
            truncated=truncated,
        )

    def preview_json(self, value: Any, *, limit: int) -> Preview:
        return self.preview(canonical_json(value), limit=limit)

    def redact_value(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.redact(value)
        if isinstance(value, dict):
            return {str(key): self.redact_value(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.redact_value(item) for item in value]
        return value


__all__ = ["Preview", "Redactor", "canonical_json", "sha256_text"]
