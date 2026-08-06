from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any


SENSITIVE_KEY = re.compile(r"(token|secret|password|passwd|api[_-]?key|authorization|cookie)", re.I)
REDACTED = "***"


def redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): REDACTED if SENSITIVE_KEY.search(str(key)) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [redact(item) for item in value]
    return value


def safe_json_preview(value: Any, limit: int = 2_000) -> str:
    try:
        rendered = json.dumps(redact(value), ensure_ascii=False, sort_keys=True, default=str)
    except Exception:
        rendered = "<无法序列化的参数>"
    if len(rendered) <= limit:
        return rendered
    return rendered[: limit - 1] + "…"


def sanitize_external_text(text: str, secrets: Sequence[str] = (), limit: int = 500) -> str:
    clean = text.replace("\r", " ").replace("\n", " ")
    for secret in secrets:
        if secret:
            clean = clean.replace(secret, REDACTED)
    clean = " ".join(clean.split())
    return clean if len(clean) <= limit else clean[: limit - 1] + "…"
