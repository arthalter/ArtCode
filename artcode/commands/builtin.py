from __future__ import annotations

from .base import CommandRegistry, CommandResult


HELP_TEXT = "/exit\n/quit\n/help"


def create_default_registry() -> CommandRegistry:
    registry = CommandRegistry()
    registry.register("/exit", _exit)
    registry.register("/quit", _exit)
    registry.register("/help", _help)
    return registry


def _exit(command: str) -> CommandResult:
    return CommandResult(action="exit")


def _help(command: str) -> CommandResult:
    return CommandResult(action="help", message=HELP_TEXT)
