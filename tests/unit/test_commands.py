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

    assert result is not None
    assert result.action == "help"
    assert "/permission [default|edit|full]" in result.message
    assert "/sandbox [auto|ask|off]" in result.message


def test_slash_word_inside_normal_text_does_not_trigger() -> None:
    registry = create_default_registry()

    assert registry.handle("请解释 /help 是什么意思") is None
    assert registry.handle("/help\n再问一句") is None


def test_registry_can_be_extended() -> None:
    registry = CommandRegistry()
    registry.register("/clear", lambda command: CommandResult(action="clear", message=command))

    assert registry.handle("/clear") == CommandResult(action="clear", message="/clear")


def test_plan_command_requires_argument() -> None:
    registry = create_default_registry()

    result = registry.handle("/plan")

    assert result.action == "help"
    assert "任务描述" in result.message


def test_plan_command_captures_argument() -> None:
    registry = create_default_registry()

    assert registry.handle("/plan 给项目加 Agent Loop") == CommandResult(
        action="plan",
        argument="给项目加 Agent Loop",
    )


def test_do_command_accepts_optional_argument() -> None:
    registry = create_default_registry()

    assert registry.handle("/do") == CommandResult(action="do")
    assert registry.handle("/do 不要运行测试") == CommandResult(action="do", argument="不要运行测试")


def test_permission_and_sandbox_commands_capture_optional_values() -> None:
    registry = create_default_registry()
    assert registry.handle("/permission full") == CommandResult(action="permission", argument="full")
    assert registry.handle("/sandbox ask") == CommandResult(action="sandbox", argument="ask")
