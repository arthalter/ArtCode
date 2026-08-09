from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Awaitable, Callable, Protocol

if TYPE_CHECKING:
    from artcode.agent import AgentMode

    from .registry import CommandRegistry


class CommandType(StrEnum):
    LOCAL = "local"
    UI_STATE = "ui_state"
    AI = "ai"


class CommandFlow(StrEnum):
    CONTINUE = "continue"
    EXIT = "exit"


class DisplayMode(StrEnum):
    DEFAULT = "DEFAULT"
    PLAN = "PLAN"


class InputRoute(StrEnum):
    EMPTY = "empty"
    MESSAGE = "message"
    COMMAND = "command"


@dataclass(frozen=True)
class CommandInvocation:
    identifier: str
    normalized_identifier: str
    argument: str
    raw_input: str


@dataclass(frozen=True)
class ParsedInput:
    route: InputRoute
    message: str = ""
    invocation: CommandInvocation | None = None


class CommandController(Protocol):
    def show_command_message(self, message: str) -> None: ...

    def clear_screen(self) -> None: ...

    def refresh_status(self) -> None: ...

    async def send_user_message(self, content: str, mode: AgentMode) -> None: ...

    async def compact_context(self) -> None: ...

    def get_recent_plan(self) -> str | None: ...

    def handle_permission(self, argument: str) -> None: ...

    async def handle_sandbox(self, argument: str) -> None: ...

    def show_sessions(self) -> None: ...

    def show_memory(self) -> None: ...


@dataclass(frozen=True)
class CommandExecutionContext:
    registry: CommandRegistry
    controller: CommandController


CommandHandler = Callable[
    [CommandInvocation, CommandExecutionContext],
    Awaitable[CommandFlow],
]


@dataclass(frozen=True)
class CommandDefinition:
    name: str
    aliases: tuple[str, ...]
    description: str
    usage: tuple[str, ...]
    command_type: CommandType
    handler: CommandHandler
    argument_hint: str | None = None
    hidden: bool = False
