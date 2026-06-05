from __future__ import annotations

from artcode.commands import CommandResult, create_default_registry
from artcode.commands.base import CommandRegistry


def test_exit_and_quit_commands_request_exit() -> None:
    registry = create_default_registry()

    assert registry.handle("/exit").should_exit is True
    assert registry.handle("/quit").should_exit is True


def test_help_command_returns_minimal_help() -> None:
    registry = create_default_registry()
    result = registry.handle("/help")

    assert result == CommandResult(action="help", message="/exit\n/quit\n/help")


def test_slash_word_inside_normal_text_does_not_trigger() -> None:
    registry = create_default_registry()

    assert registry.handle("请解释 /help 是什么意思") is None
    assert registry.handle("/help\n再问一句") is None


def test_registry_can_be_extended() -> None:
    registry = CommandRegistry()
    registry.register("/clear", lambda command: CommandResult(action="clear", message=command))

    assert registry.handle("/clear") == CommandResult(action="clear", message="/clear")
