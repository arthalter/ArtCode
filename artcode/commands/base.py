from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


CommandHandler = Callable[[str], "CommandResult"]


@dataclass(frozen=True)
class CommandResult:
    action: str
    message: str = ""

    @property
    def should_exit(self) -> bool:
        return self.action == "exit"


class CommandRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, CommandHandler] = {}

    def register(self, name: str, handler: CommandHandler) -> None:
        normalized = name.strip()
        if not normalized.startswith("/"):
            raise ValueError("Slash command names must start with '/'.")
        self._handlers[normalized] = handler

    def handle(self, user_input: str) -> CommandResult | None:
        command = user_input.strip()
        if "\n" in command:
            return None
        handler = self._handlers.get(command)
        if handler is None:
            return None
        return handler(command)
