from __future__ import annotations

from datetime import datetime, timezone

from hypothesis import HealthCheck, given, settings, strategies as st
import pytest

from artcode.conversation import ConversationContext
from artcode.persistence.sessions import SessionJournal, SessionRecovery, _valid_message
from artcode.providers.tool_calls import ToolCall
from artcode.tools.results import success_result

pytestmark = [pytest.mark.ch10_5, pytest.mark.property]
safe_text = st.text(alphabet=st.characters(exclude_categories=("Cs",)), max_size=2_000)


@given(safe_text.filter(bool))
def test_arbitrary_nonempty_reasoning_round_trips_in_memory(reasoning: str) -> None:
    context = ConversationContext("system")
    call = ToolCall("c", "t", "{}")
    context.append_assistant_tool_call((call,), reasoning_content=reasoning)
    context.append_tool_result(call, success_result("t", "ok", "x"))
    assert context.export_messages()[-2]["reasoning_content"] == reasoning


@given(safe_text)
def test_arbitrary_visible_assistant_text_never_gains_reasoning(text: str) -> None:
    context = ConversationContext("system")
    context.append_assistant(text)
    assert "reasoning_content" not in context.export_messages()[-1]


@given(st.lists(safe_text, min_size=1, max_size=20))
def test_user_message_sequence_is_unchanged_by_tool_reasoning(users: list[str]) -> None:
    context = ConversationContext("system")
    for index, user in enumerate(users):
        context.append_user(user)
        call = ToolCall(f"c{index}", "read_file", "{}")
        context.append_assistant_tool_call((call,), reasoning_content=f"r{index}")
        context.append_tool_result(call, success_result("read_file", "ok", "x"))
    assert [message["content"] for message in context.export_messages() if message["role"] == "user"] == users


@given(st.integers(min_value=1, max_value=30))
def test_any_supported_tool_call_count_keeps_unique_ids(count: int) -> None:
    calls = tuple(ToolCall(f"c{i}", f"t{i}", "{}") for i in range(count))
    context = ConversationContext("system")
    context.append_assistant_tool_call(calls, reasoning_content="r")
    ids = [item["id"] for item in context.export_messages()[-1]["tool_calls"]]
    assert ids == [f"c{i}" for i in range(count)]


@given(safe_text.filter(bool))
@settings(max_examples=20, suppress_health_check=(HealthCheck.function_scoped_fixture,))
def test_arbitrary_reasoning_round_trips_through_jsonl(tmp_path, reasoning: str) -> None:
    journal = SessionJournal.create(tmp_path, datetime(2026, 8, 9, tzinfo=timezone.utc))
    context = ConversationContext("system", observer=journal)
    call = ToolCall("c", "t", "{}")
    context.append_assistant_tool_call((call,), reasoning_content=reasoning)
    context.append_tool_result(call, success_result("t", "ok", "x"))
    path = journal.path
    journal.close()
    report = SessionRecovery().recover(path)
    assert report.records[0].message["reasoning_content"] == reasoning


@given(st.one_of(st.none(), st.booleans(), st.integers(), st.floats(allow_nan=False), st.lists(st.integers())))
def test_all_generated_non_string_reasoning_values_are_invalid(value) -> None:
    message = {
        "role": "assistant",
        "content": "",
        "reasoning_content": value,
        "tool_calls": [{"id": "c", "type": "function", "function": {"name": "t", "arguments": "{}"}}],
    }
    assert _valid_message(message) is False


@given(safe_text)
def test_export_mutation_never_changes_saved_reasoning(reasoning: str) -> None:
    context = ConversationContext("system")
    context.append_assistant_tool_call((ToolCall("c", "t", "{}"),), reasoning_content=reasoning)
    exported = context.export_messages()
    exported[-1]["reasoning_content"] = "changed"
    expected = reasoning if reasoning else None
    assert context.export_messages()[-1].get("reasoning_content") == expected


@given(safe_text.filter(bool))
def test_repairing_missing_tool_result_preserves_reasoning(reasoning: str) -> None:
    context = ConversationContext("system")
    context.append_assistant_tool_call((ToolCall("c", "t", "{}"),), reasoning_content=reasoning)
    context.repair_incomplete_tool_calls()
    assert context.export_messages()[1]["reasoning_content"] == reasoning
    assert context.export_messages()[2]["tool_call_id"] == "c"
