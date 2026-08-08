from __future__ import annotations

from .base import CommandInvocation, InputRoute, ParsedInput


def parse_input(raw: str) -> ParsedInput:
    if not raw.strip():
        return ParsedInput(InputRoute.EMPTY)

    candidate = raw.lstrip()
    if not candidate.startswith("/"):
        return ParsedInput(InputRoute.MESSAGE, message=raw)

    parts = candidate.split(maxsplit=1)
    identifier = parts[0]
    argument = parts[1].strip() if len(parts) == 2 else ""
    return ParsedInput(
        InputRoute.COMMAND,
        invocation=CommandInvocation(
            identifier=identifier,
            normalized_identifier=identifier.lower(),
            argument=argument,
            raw_input=raw,
        ),
    )
