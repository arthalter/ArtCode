from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from artcode.agent.events import CompletedTurn, ModelTurn, NaturalTurn
from artcode.conversation import ConversationContext
from artcode.persistence.sessions import _valid_message
from artcode.providers.events import TokenUsage
from artcode.providers.tool_calls import ToolCall

pytestmark = pytest.mark.ch10_5


@pytest.mark.parametrize(
    "reasoning",
    [
        "r",
        "推理",
        "line1\nline2",
        " leading",
        "trailing ",
        "{json-like}",
        "emoji 🧠",
        "tabs\tinside",
        "quoted \"value\"",
        "slash\\path",
        "null-like null",
        "zero 0",
        "mixed 中文 ASCII",
        "\u2028separator",
        "x" * 4096,
    ],
    ids=(
        "ascii", "unicode", "newline", "leading", "trailing", "json", "emoji", "tab",
        "quote", "slash", "null", "zero", "mixed", "separator", "long",
    ),
)
def test_reasoning_is_saved_only_on_assistant_tool_message(reasoning: str) -> None:
    context = ConversationContext("system")
    context.append_assistant_tool_call(
        (ToolCall("call-1", "read_file", "{}"),),
        reasoning_content=reasoning,
    )
    assert context.export_messages()[-1]["reasoning_content"] == reasoning


def test_empty_reasoning_is_omitted() -> None:
    context = ConversationContext("system")
    context.append_assistant_tool_call((ToolCall("call-1", "read_file", "{}"),))
    assert "reasoning_content" not in context.export_messages()[-1]


@pytest.mark.parametrize("count", [1, 2, 3, 4, 5])
def test_tool_call_sequence_and_ids_are_preserved(count: int) -> None:
    calls = tuple(ToolCall(f"call-{index}", f"tool_{index}", f'{{"index":{index}}}') for index in range(count))
    context = ConversationContext("system")
    context.append_assistant_tool_call(calls, reasoning_content="reason")
    raw = context.export_messages()[-1]["tool_calls"]
    assert [item["id"] for item in raw] == [call.id for call in calls]
    assert [item["function"]["arguments"] for item in raw] == [call.arguments_json for call in calls]


@pytest.mark.parametrize(
    "value",
    [None, True, False, 1, 1.5, [], {}, object()],
    ids=("none", "true", "false", "int", "float", "list", "map", "object"),
)
def test_session_message_rejects_non_string_reasoning(value) -> None:
    message = {
        "role": "assistant",
        "content": "",
        "reasoning_content": value,
        "tool_calls": [
            {"id": "call-1", "type": "function", "function": {"name": "read_file", "arguments": "{}"}}
        ],
    }
    assert _valid_message(message) is False


@pytest.mark.parametrize("finish", [None, "stop", "length", "tool_calls", "content_filter"])
def test_model_turn_preserves_finish_reason(finish: str | None) -> None:
    turn = ModelTurn("text", "reason", (), TokenUsage(total_tokens=3), finish)
    assert turn.finish_reason == finish
    assert turn.reasoning_content == "reason"


@pytest.mark.parametrize("mode", ["normal", "plan", "do", "NORMAL", "custom"])
def test_completed_turn_is_the_natural_turn_compatibility_type(mode: str) -> None:
    turn = CompletedTurn("session", mode, "user", "final", ("msg-1",), ())
    assert isinstance(turn, NaturalTurn)
    with pytest.raises(FrozenInstanceError):
        turn.mode = "changed"  # type: ignore[misc]


def test_normal_assistant_message_never_stores_reasoning() -> None:
    context = ConversationContext("system")
    context.append_assistant("visible")
    assert context.export_messages()[-1] == {"role": "assistant", "content": "visible"}


def test_exported_reasoning_message_is_a_deep_copy() -> None:
    context = ConversationContext("system")
    context.append_assistant_tool_call((ToolCall("call", "read_file", "{}"),), reasoning_content="original")
    exported = context.export_messages()
    exported[-1]["reasoning_content"] = "mutated"
    assert context.export_messages()[-1]["reasoning_content"] == "original"
