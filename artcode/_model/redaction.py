from __future__ import annotations


def scrub(text: object, secrets: tuple[str, ...]) -> str:
    safe = str(text)
    for secret in secrets:
        if secret:
            safe = safe.replace(secret, "[REDACTED]")
    return safe
