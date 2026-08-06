from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from .models import TokenAnchor


class TokenEstimator:
    def __init__(self) -> None:
        self.anchor: TokenAnchor | None = None

    def estimate_request(
        self,
        messages: Sequence[dict[str, Any]],
        tools: Sequence[dict[str, Any]] | None,
    ) -> int:
        heuristic = self.heuristic_request_tokens(messages, tools)
        if self.anchor is None:
            return heuristic
        return max(
            self.anchor.prompt_tokens + heuristic - self.anchor.heuristic_tokens,
            0,
        )

    def heuristic_request_tokens(
        self,
        messages: Sequence[dict[str, Any]],
        tools: Sequence[dict[str, Any]] | None,
    ) -> int:
        payload: dict[str, Any] = {"messages": list(messages)}
        if tools is not None:
            payload["tools"] = list(tools)
        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return estimate_text_tokens(serialized)

    def record_usage(
        self,
        prompt_tokens: int,
        messages: Sequence[dict[str, Any]],
        tools: Sequence[dict[str, Any]] | None,
    ) -> None:
        if isinstance(prompt_tokens, bool) or prompt_tokens < 0:
            return
        self.anchor = TokenAnchor(
            prompt_tokens=prompt_tokens,
            heuristic_tokens=self.heuristic_request_tokens(messages, tools),
        )


def estimate_text_tokens(text: str) -> int:
    cjk = 0
    other = 0
    for character in text:
        if _is_cjk(character):
            cjk += 1
        else:
            other += 1
    return cjk + (other + 2) // 3


def _is_cjk(character: str) -> bool:
    codepoint = ord(character)
    ranges = (
        (0x3400, 0x4DBF),
        (0x4E00, 0x9FFF),
        (0xF900, 0xFAFF),
        (0x20000, 0x2FA1F),
    )
    return any(start <= codepoint <= end for start, end in ranges)
