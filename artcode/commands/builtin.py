from __future__ import annotations

from .base import CommandRegistry, CommandResult


HELP_TEXT = "/exit\n/quit\n/help\n/plan 任务描述\n/do [附加说明]"


def create_default_registry() -> CommandRegistry:
    registry = CommandRegistry()
    registry.register("/exit", _exit)
    registry.register("/quit", _exit)
    registry.register("/help", _help)
    registry.register("/plan", _plan)
    registry.register("/do", _do)
    return registry


def _exit(command: str) -> CommandResult:
    return CommandResult(action="exit")


def _help(command: str) -> CommandResult:
    return CommandResult(action="help", message=HELP_TEXT)


def _plan(command: str) -> CommandResult:
    _, _, argument = command.partition(" ")
    argument = argument.strip()
    if not argument:
        return CommandResult(action="help", message="请使用 /plan 任务描述。")
    return CommandResult(action="plan", argument=argument)


def _do(command: str) -> CommandResult:
    _, _, argument = command.partition(" ")
    return CommandResult(action="do", argument=argument.strip())
