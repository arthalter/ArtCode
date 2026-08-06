from __future__ import annotations

from artcode.context_management.retention import RetentionPlanner
from artcode.conversation import ConversationContext
from artcode.providers.tool_calls import ToolCall
from artcode.tools import success_result


def add_messages(context: ConversationContext, count: int, size: int = 30) -> None:
    for index in range(count):
        if index % 2 == 0:
            context.append_user(f"u{index}-" + "a" * size)
        else:
            context.append_assistant(f"a{index}-" + "b" * size)


def test_short_history_has_no_compactable_prefix() -> None:
    context = ConversationContext("system")
    add_messages(context, 4)

    plan = RetentionPlanner(recent_token_budget=1000, minimum_messages=5).plan(context.snapshot())

    assert plan.can_compact is False
    assert len(plan.recent_entries) == 4


def test_retains_budget_and_at_least_five_messages() -> None:
    context = ConversationContext("system")
    add_messages(context, 12, size=100)

    plan = RetentionPlanner(recent_token_budget=150, minimum_messages=5).plan(context.snapshot())

    assert plan.can_compact
    assert len(plan.recent_entries) >= 5
    assert plan.recent_entries[-1].payload["content"].startswith("a11")


def test_tool_call_group_is_never_split() -> None:
    context = ConversationContext("system")
    add_messages(context, 5)
    calls = [ToolCall("c1", "read_file", "{}"), ToolCall("c2", "read_file", "{}")]
    context.append_assistant_tool_call(calls)
    for call in calls:
        context.append_tool_result(call, success_result("read_file", "ok", "x" * 30))
    context.append_assistant("after")

    plan = RetentionPlanner(recent_token_budget=1, minimum_messages=2).plan(context.snapshot())
    recent_roles = [entry.payload["role"] for entry in plan.recent_entries]

    assert recent_roles[-4:] == ["assistant", "tool", "tool", "assistant"]


def test_existing_summary_ids_merge_with_new_user_ids() -> None:
    context = ConversationContext("system")
    old_summary = context.make_entry(
        {"role": "system", "content": "<conversation-summary>old</conversation-summary>"},
        summarized_user_ids=("old-u1", "old-u2"),
    )
    snapshot = context.snapshot()
    assert context.replace_entries_if_version(snapshot.version, (snapshot.entries[0], old_summary))
    add_messages(context, 10, size=100)

    plan = RetentionPlanner(recent_token_budget=100, minimum_messages=3).plan(context.snapshot())

    assert plan.summarized_user_ids[:2] == ("old-u1", "old-u2")
    assert len(plan.summarized_user_ids) > 2


def test_persistence_failed_entry_is_forced_into_recent_region() -> None:
    context = ConversationContext("system")
    add_messages(context, 3, size=100)
    call = ToolCall("c1", "read_file", "{}")
    context.append_assistant_tool_call([call])
    context.append_tool_result(call, success_result("read_file", "ok", "protected"))
    protected_id = context.snapshot().entries[-1].id
    context.mark_persistence_failed(protected_id)
    add_messages(context, 10, size=100)

    plan = RetentionPlanner(recent_token_budget=100, minimum_messages=3).plan(context.snapshot())
    recent_ids = {entry.id for entry in plan.recent_entries}

    assert protected_id in recent_ids
    assert any(entry.payload.get("tool_calls") for entry in plan.recent_entries)
