from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


CommandHandler = Callable[[str], "CommandResult"]


@dataclass(frozen=True)
class CommandResult:
    action: str
    message: str = ""
    argument: str = ""

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
        if not command.startswith("/"):
            return None
        name, _, argument = command.partition(" ")
        handler = self._handlers.get(name)
        if handler is None:
            return None
        result = handler(command)
        if result.argument:
            return result
        return CommandResult(result.action, result.message, argument.strip())
