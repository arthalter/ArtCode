from __future__ import annotations

import asyncio

import pytest
from hypothesis import given, settings, strategies as st

from artcode.context_management import ContextSummarizer
from artcode.context_management.retention import RetentionPlanner
from artcode.context_management.summarizer import SUMMARY_TITLES, VERBATIM_PLACEHOLDER
from artcode.conversation import ConversationContext
from artcode.providers.events import content_delta_event, done_event
from artcode.providers.tool_calls import ToolCall
from artcode.tools import success_result

pytestmark = [pytest.mark.ch10_5, pytest.mark.property]

SAFE_TEXT = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",), blacklist_characters=("\x00",)),
    max_size=80,
)


def valid_summary() -> str:
    sections = [
        f"## {index}. {title}\n{VERBATIM_PLACEHOLDER if index == 6 else 'internal'}"
        for index, title in enumerate(SUMMARY_TITLES, start=1)
    ]
    return "<analysis>draft</analysis><summary>" + "\n\n".join(sections) + "</summary>"


class Provider:
    async def stream_chat(self, messages, tools=None, *, options=None):
        yield content_delta_event(valid_summary())
        yield done_event()


def users(context: ConversationContext):
    return tuple(
        (entry.id, entry.payload["content"])
        for entry in context.snapshot().entries
        if entry.payload.get("role") == "user"
    )


@given(messages=st.lists(st.tuples(st.sampled_from(("user", "assistant", "system")), SAFE_TEXT), min_size=8, max_size=40))
@settings(max_examples=60)
def test_any_history_partition_preserves_every_user_in_order(messages) -> None:
    context = ConversationContext("fixed")
    for role, content in messages:
        if role == "user":
            context.append_user(content)
        elif role == "assistant":
            context.append_assistant(content)
        else:
            entry = context.make_entry({"role": "system", "content": content})
            snapshot = context.snapshot()
            context.replace_entries_if_version(snapshot.version, (*snapshot.entries, entry))
    expected = users(context)

    plan = RetentionPlanner(1, 2).plan(context.snapshot())
    retained = tuple(
        (entry.id, entry.payload["content"])
        for entry in (*plan.preserved_user_entries, *plan.recent_entries)
        if entry.payload.get("role") == "user"
    )

    assert retained == expected


@given(turns=st.integers(min_value=4, max_value=30), budget=st.integers(min_value=1, max_value=500))
@settings(max_examples=60)
def test_retention_plan_is_deterministic_for_same_snapshot(turns, budget) -> None:
    context = ConversationContext("fixed")
    for index in range(turns):
        context.append_user(f"u-{index}")
        context.append_assistant("a" * 100)
    snapshot = context.snapshot()
    planner = RetentionPlanner(budget, 2)

    assert planner.plan(snapshot) == planner.plan(snapshot)


@given(contents=st.lists(SAFE_TEXT, min_size=6, max_size=20))
@settings(max_examples=30)
def test_generated_user_text_survives_real_summary_commit(contents) -> None:
    context = ConversationContext("fixed")
    for content in contents:
        context.append_user(content)
        context.append_assistant("answer" * 30)
    before = users(context)
    snapshot = context.snapshot()
    plan = RetentionPlanner(1, 2).plan(snapshot)

    result = asyncio.run(ContextSummarizer(Provider(), context).summarize(snapshot, plan))

    assert result.succeeded
    assert users(context) == before


@given(cycles=st.integers(min_value=1, max_value=5), seed=SAFE_TEXT)
@settings(max_examples=20)
def test_generated_repeated_compaction_keeps_user_hash_equivalent(cycles, seed) -> None:
    async def scenario() -> None:
        context = ConversationContext("fixed")
        for cycle in range(cycles):
            for index in range(5):
                context.append_user(f"{seed}:{cycle}:{index}")
                context.append_assistant("answer" * 40)
            before = users(context)
            snapshot = context.snapshot()
            plan = RetentionPlanner(1, 2).plan(snapshot)
            result = await ContextSummarizer(Provider(), context).summarize(snapshot, plan)
            assert result.succeeded
            assert users(context) == before

    asyncio.run(scenario())


@given(old_turns=st.integers(min_value=2, max_value=10), recent_turns=st.integers(min_value=1, max_value=5))
@settings(max_examples=40)
def test_tool_call_result_units_are_never_split_by_generated_retention(old_turns, recent_turns) -> None:
    context = ConversationContext("fixed")
    for index in range(old_turns):
        context.append_user(f"old-{index}")
        context.append_assistant("old-answer" * 20)
    for index in range(recent_turns):
        call = ToolCall(f"call-{index}", "read_file", "{}")
        context.append_assistant_tool_call((call,))
        context.append_tool_result(call, success_result("read_file", "ok", "value"))
    plan = RetentionPlanner(1, 2).plan(context.snapshot())
    recent = plan.recent_entries

    for index, entry in enumerate(recent):
        if isinstance(entry.payload.get("tool_calls"), list):
            expected_ids = {item["id"] for item in entry.payload["tool_calls"]}
            actual_ids = set()
            cursor = index + 1
            while cursor < len(recent) and recent[cursor].payload.get("role") == "tool":
                actual_ids.add(recent[cursor].payload["tool_call_id"])
                cursor += 1
            assert actual_ids == expected_ids
