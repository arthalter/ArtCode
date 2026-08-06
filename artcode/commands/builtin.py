from __future__ import annotations

from .base import CommandRegistry, CommandResult


HELP_TEXT = (
    "/exit\n/quit\n/help\n/plan 任务描述\n/do [附加说明]\n/compact\n"
    "/permission [default|edit|full]\n/sandbox [auto|ask|off]"
    "\n/sessions\n/memory"
)


def create_default_registry() -> CommandRegistry:
    registry = CommandRegistry()
    registry.register("/exit", _exit)
    registry.register("/quit", _exit)
    registry.register("/help", _help)
    registry.register("/plan", _plan)
    registry.register("/do", _do)
    registry.register("/compact", _compact)
    registry.register("/permission", _permission)
    registry.register("/sandbox", _sandbox)
    registry.register("/sessions", _sessions)
    registry.register("/memory", _memory)
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


def _compact(command: str) -> CommandResult:
    _, _, argument = command.partition(" ")
    if argument.strip():
        return CommandResult(action="help", message="/compact 不接受参数。")
    return CommandResult(action="compact")


def _permission(command: str) -> CommandResult:
    _, _, argument = command.partition(" ")
    return CommandResult(action="permission", argument=argument.strip())


def _sandbox(command: str) -> CommandResult:
    _, _, argument = command.partition(" ")
    return CommandResult(action="sandbox", argument=argument.strip())


def _sessions(command: str) -> CommandResult:
    _, _, argument = command.partition(" ")
    if argument.strip():
        return CommandResult(action="help", message="/sessions 不接受参数。")
    return CommandResult(action="sessions")


def _memory(command: str) -> CommandResult:
    _, _, argument = command.partition(" ")
    if argument.strip():
        return CommandResult(action="help", message="/memory 不接受参数。")
    return CommandResult(action="memory")
