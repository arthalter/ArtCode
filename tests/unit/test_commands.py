from __future__ import annotations

from dataclasses import dataclass, field, replace
import subprocess
import sys

import pytest

from artcode.agent import TokenUsage
from artcode.commands import (
    CommandDefinition,
    CommandDispatcher,
    CommandFlow,
    CommandRegistrationError,
    CommandRegistry,
    CommandType,
    DisplayMode,
    InputRoute,
    create_default_registry,
    parse_input,
)


@dataclass
class FakeController:
    messages: list[str] = field(default_factory=list)
    sent: list[tuple[str, str]] = field(default_factory=list)
    calls: list[tuple[str, str]] = field(default_factory=list)
    plan: str | None = "最近计划"
    usage: TokenUsage | None = None

    def show_command_message(self, message: str) -> None:
        self.messages.append(message)

    def clear_screen(self) -> None:
        self.calls.append(("clear", ""))

    def set_display_mode(self, mode: DisplayMode) -> None:
        self.calls.append(("mode", mode.value))

    def get_token_usage(self) -> TokenUsage | None:
        return self.usage

    def refresh_status(self) -> None:
        self.calls.append(("status", ""))

    async def send_user_message(self, content: str, mode) -> None:
        self.sent.append((content, mode.name))

    async def compact_context(self) -> None:
        self.calls.append(("compact", ""))

    def get_recent_plan(self) -> str | None:
        return self.plan

    def handle_permission(self, argument: str) -> None:
        self.calls.append(("permission", argument))

    async def handle_sandbox(self, argument: str) -> None:
        self.calls.append(("sandbox", argument))

    def show_sessions(self) -> None:
        self.calls.append(("sessions", ""))

    def show_memory(self) -> None:
        self.calls.append(("memory", ""))


async def _continue_handler(invocation, context) -> CommandFlow:
    context.controller.show_command_message(invocation.argument)
    return CommandFlow.CONTINUE


def _definition(
    name: str = "/test",
    *,
    aliases: tuple[str, ...] = (),
    hidden: bool = False,
) -> CommandDefinition:
    return CommandDefinition(
        name=name,
        aliases=aliases,
        description="测试命令",
        usage=(f"{name} [值]",),
        command_type=CommandType.LOCAL,
        handler=_continue_handler,
        argument_hint="[值]",
        hidden=hidden,
    )


@pytest.mark.parametrize("raw", ["", " ", "\t\n  "])
def test_parser_classifies_empty_input(raw: str) -> None:
    parsed = parse_input(raw)
    assert parsed.route is InputRoute.EMPTY
    assert parsed.invocation is None


@pytest.mark.parametrize("raw", ["你好", "  你好", "请解释 /help"])
def test_parser_preserves_normal_messages(raw: str) -> None:
    parsed = parse_input(raw)
    assert parsed.route is InputRoute.MESSAGE
    assert parsed.message == raw


@pytest.mark.parametrize(
    ("raw", "identifier", "argument"),
    [
        ("/HeLp", "/HeLp", ""),
        (" /plan\t写测试", "/plan", "写测试"),
        ("/plan 第一行\n第二行", "/plan", "第一行\n第二行"),
        ("/unknown\n下一行\n再下一行", "/unknown", "下一行\n再下一行"),
    ],
)
def test_parser_keeps_every_slash_input_on_command_route(
    raw: str,
    identifier: str,
    argument: str,
) -> None:
    parsed = parse_input(raw)
    assert parsed.route is InputRoute.COMMAND
    assert parsed.invocation is not None
    assert parsed.invocation.identifier == identifier
    assert parsed.invocation.normalized_identifier == identifier.lower()
    assert parsed.invocation.argument == argument
    assert parsed.invocation.raw_input == raw


def test_registry_resolves_name_and_alias_case_insensitively() -> None:
    registry = CommandRegistry()
    definition = _definition("/Test", aliases=("/T",))
    registry.register(definition)

    assert registry.resolve("/test") is definition
    assert registry.resolve(" /t ") is definition
    assert registry.definitions() == (definition,)


@pytest.mark.parametrize(
    ("first", "second"),
    [
        (_definition("/one"), _definition("/ONE")),
        (_definition("/one", aliases=("/shared",)), _definition("/shared")),
        (_definition("/one"), _definition("/two", aliases=("/ONE",))),
        (_definition("/one", aliases=("/shared",)), _definition("/two", aliases=("/SHARED",))),
    ],
)
def test_registry_rejects_all_cross_definition_conflicts(first, second) -> None:
    registry = CommandRegistry()
    registry.register(first)

    with pytest.raises(CommandRegistrationError) as raised:
        registry.register(second)

    assert "/" in str(raised.value)
    assert registry.definitions(include_hidden=True) == (first,)


def test_registry_rejects_duplicate_identifiers_inside_one_definition_atomically() -> None:
    registry = CommandRegistry()
    with pytest.raises(CommandRegistrationError):
        registry.register(_definition("/one", aliases=("/ONE",)))
    assert registry.definitions(include_hidden=True) == ()


@pytest.mark.parametrize(
    "name",
    ["test", " /test", "/bad name", "/bad\tname", "/bad\nname"],
)
def test_registry_rejects_invalid_identifiers(name: str) -> None:
    with pytest.raises(CommandRegistrationError):
        CommandRegistry().register(_definition(name))


@pytest.mark.parametrize(
    "definition",
    [
        replace(_definition(), description=""),
        replace(_definition(), usage=()),
        replace(_definition(), handler=None),
    ],
)
def test_registry_rejects_incomplete_metadata(definition) -> None:
    with pytest.raises(CommandRegistrationError):
        CommandRegistry().register(definition)


def test_failed_alias_validation_leaves_no_partial_index_entries() -> None:
    registry = CommandRegistry()
    invalid = _definition("/new", aliases=("/valid-alias", "bad-alias"))

    with pytest.raises(CommandRegistrationError):
        registry.register(invalid)

    assert registry.resolve("/new") is None
    assert registry.resolve("/valid-alias") is None
    assert registry.definitions(include_hidden=True) == ()


def test_registry_hides_definitions_only_from_default_enumeration() -> None:
    registry = CommandRegistry()
    visible = _definition("/visible")
    hidden = _definition("/hidden", hidden=True)
    registry.register(visible)
    registry.register(hidden)

    assert registry.definitions() == (visible,)
    assert registry.definitions(include_hidden=True) == (visible, hidden)
    assert registry.resolve("/hidden") is hidden


async def test_dispatcher_calls_handler_by_alias() -> None:
    registry = CommandRegistry()
    registry.register(_definition(aliases=("/alias",)))
    invocation = parse_input("/ALIAS 多行\n参数").invocation
    controller = FakeController()

    result = await CommandDispatcher(registry).dispatch(invocation, controller)

    assert result is CommandFlow.CONTINUE
    assert controller.messages == ["多行\n参数"]


async def test_dispatcher_handles_unknown_command_locally() -> None:
    controller = FakeController()
    invocation = parse_input("/Missing\n内容").invocation

    result = await CommandDispatcher(CommandRegistry()).dispatch(invocation, controller)

    assert result is CommandFlow.CONTINUE
    assert "/Missing" in controller.messages[0]
    assert "/help" in controller.messages[0]
    assert controller.sent == []


async def test_dispatcher_does_not_swallow_handler_exceptions_or_fallback_to_agent() -> None:
    async def fail(invocation, context):
        raise RuntimeError("handler failed")

    registry = CommandRegistry()
    registry.register(replace(_definition(), handler=fail))
    controller = FakeController()

    with pytest.raises(RuntimeError, match="handler failed"):
        await CommandDispatcher(registry).dispatch(parse_input("/test").invocation, controller)

    assert controller.sent == []


def test_command_package_import_does_not_load_ui_frameworks() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import artcode.commands; "
                "assert 'rich' not in sys.modules; "
                "assert 'prompt_toolkit' not in sys.modules"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_default_registry_has_exact_public_command_metadata() -> None:
    definitions = create_default_registry().definitions()
    expected = {
        "/exit": CommandType.LOCAL,
        "/quit": CommandType.LOCAL,
        "/help": CommandType.LOCAL,
        "/plan": CommandType.AI,
        "/do": CommandType.AI,
        "/compact": CommandType.LOCAL,
        "/permission": CommandType.UI_STATE,
        "/sandbox": CommandType.UI_STATE,
        "/sessions": CommandType.LOCAL,
        "/memory": CommandType.LOCAL,
        "/clear": CommandType.UI_STATE,
        "/status": CommandType.LOCAL,
    }

    assert {definition.name: definition.command_type for definition in definitions} == expected
    assert all(definition.aliases == () for definition in definitions)
    assert all(not definition.hidden for definition in definitions)
    assert all(definition.description and definition.usage for definition in definitions)


async def _dispatch(raw: str, controller: FakeController | None = None):
    registry = create_default_registry()
    selected = controller or FakeController()
    invocation = parse_input(raw).invocation
    result = await CommandDispatcher(registry).dispatch(invocation, selected)
    return result, selected


async def test_exit_and_quit_request_exit_without_becoming_aliases() -> None:
    exit_result, _ = await _dispatch("/EXIT")
    quit_result, _ = await _dispatch("/quit")
    assert exit_result is CommandFlow.EXIT
    assert quit_result is CommandFlow.EXIT


async def test_help_is_generated_from_registry_metadata_and_hides_hidden_commands() -> None:
    registry = create_default_registry()
    registry.register(_definition("/secret", hidden=True))
    controller = FakeController()

    await CommandDispatcher(registry).dispatch(parse_input("/help").invocation, controller)

    output = controller.messages[-1]
    assert "/status" in output
    assert "/clear" in output
    assert "/secret" not in output

    await CommandDispatcher(registry).dispatch(parse_input("/help /secret").invocation, controller)
    assert "命令：/secret" in controller.messages[-1]
    assert "隐藏：是" in controller.messages[-1]


async def test_help_overview_preserves_registry_order() -> None:
    registry = create_default_registry()
    controller = FakeController()
    await CommandDispatcher(registry).dispatch(parse_input("/help").invocation, controller)

    rows = controller.messages[-1].splitlines()[1:]
    assert [row.split(" ", 1)[0] for row in rows] == [
        definition.name for definition in registry.definitions()
    ]


async def test_plan_preserves_multiline_argument_and_uses_plan_mode() -> None:
    _, controller = await _dispatch("/PlAn 第一行\n第二行")
    assert controller.sent == [("第一行\n第二行", "plan")]


async def test_plan_requires_description() -> None:
    _, controller = await _dispatch("/plan")
    assert "任务描述" in controller.messages[-1]
    assert controller.sent == []


async def test_help_details_show_plan_multiline_and_do_optional_arguments() -> None:
    registry = create_default_registry()
    controller = FakeController()
    dispatcher = CommandDispatcher(registry)

    await dispatcher.dispatch(parse_input("/help /plan").invocation, controller)
    plan_help = controller.messages[-1]
    await dispatcher.dispatch(parse_input("/help /do").invocation, controller)
    do_help = controller.messages[-1]

    assert "第一行任务\n第二行约束" in plan_help
    assert "参数：任务描述" in plan_help
    assert "参数：[附加说明]" in do_help


async def test_do_uses_recent_plan_and_optional_multiline_instruction() -> None:
    _, controller = await _dispatch("/do 先测试\n再提交")
    content, mode = controller.sent[0]
    assert "最近计划" in content
    assert "先测试\n再提交" in content
    assert mode == "do"


async def test_do_requires_recent_plan() -> None:
    controller = FakeController(plan=None)
    await _dispatch("/do", controller)
    assert "请先执行 /plan" in controller.messages[-1]
    assert controller.sent == []


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("/compact", ("compact", "")),
        ("/permission full", ("permission", "full")),
        ("/sandbox ask", ("sandbox", "ask")),
        ("/sessions", ("sessions", "")),
        ("/memory", ("memory", "")),
        ("/clear", ("clear", "")),
        ("/status", ("status", "")),
    ],
)
async def test_builtin_commands_call_only_their_controller_capability(raw, expected) -> None:
    _, controller = await _dispatch(raw)
    assert controller.calls == [expected]
    assert controller.sent == []


@pytest.mark.parametrize(
    "name",
    ["/exit", "/quit", "/compact", "/sessions", "/memory", "/clear", "/status"],
)
async def test_no_argument_commands_reject_extra_text(name: str) -> None:
    result, controller = await _dispatch(f"{name} extra")
    assert result is CommandFlow.CONTINUE
    assert "不接受参数" in controller.messages[-1]
    assert controller.calls == []
    assert controller.sent == []


@pytest.mark.ch10_5
@pytest.mark.parametrize("repeat", [1, 2, 5, 10])
async def test_repeated_status_dispatch_only_reads_status_capability(repeat: int) -> None:
    registry = create_default_registry()
    controller = FakeController()
    dispatcher = CommandDispatcher(registry)

    for _ in range(repeat):
        await dispatcher.dispatch(parse_input("/status").invocation, controller)

    assert controller.calls == [("status", "")] * repeat
    assert controller.sent == []
    assert controller.messages == []


@pytest.mark.ch10_5
def test_command_controller_protocol_excludes_runtime_state_storage() -> None:
    annotations = set(getattr(__import__("artcode.commands.base", fromlist=["CommandController"]).CommandController, "__annotations__", {}))
    assert "state" not in annotations
    assert "provider" not in annotations
