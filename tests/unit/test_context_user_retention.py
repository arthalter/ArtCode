from __future__ import annotations

from pathlib import Path

import pytest

from artcode.config import ContextConfig
from artcode.context_management import ContextArtifactStore, ContextManager, ContextSummarizer, LightweightCompactor
from artcode.context_management.models import CompressionTrigger
from artcode.context_management.retention import RetentionPlanner
from artcode.context_management.summarizer import SUMMARY_TITLES, VERBATIM_PLACEHOLDER, SummaryResult
from artcode.conversation import ConversationContext
from artcode.providers.events import content_delta_event, done_event
from artcode.providers.tool_calls import ToolCall
from artcode.tools import success_result

pytestmark = pytest.mark.ch10_5


def valid_summary() -> str:
    sections = [
        f"## {index}. {title}\n{VERBATIM_PLACEHOLDER if index == 6 else f'内部摘要 {index}'}"
        for index, title in enumerate(SUMMARY_TITLES, start=1)
    ]
    return "<analysis>draft</analysis><summary>" + "\n\n".join(sections) + "</summary>"


class SummaryProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def stream_chat(self, messages, tools=None, *, options=None):
        self.calls += 1
        yield content_delta_event(valid_summary())
        yield done_event()


def add_turns(context: ConversationContext, count: int, *, prefix: str = "turn", size: int = 120) -> None:
    for index in range(count):
        context.append_user(f"{prefix}-user-{index}-" + "u" * size)
        context.append_assistant(f"{prefix}-assistant-{index}-" + "a" * size)


def user_entries(context: ConversationContext):
    return tuple(
        entry
        for entry in context.snapshot().entries
        if entry.payload.get("role") == "user"
    )


@pytest.mark.parametrize(
    ("turns", "budget", "minimum"),
    [
        (6, 1, 1), (6, 20, 2), (8, 40, 3), (10, 80, 4),
        (12, 120, 5), (14, 200, 5), (16, 300, 6), (18, 500, 7),
        (20, 800, 8), (22, 1000, 9), (24, 1200, 10), (30, 1500, 12),
    ],
    ids=("tiny", "small", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "long"),
)
def test_retention_plan_partitions_users_from_compactable_internal_history(
    turns,
    budget,
    minimum,
) -> None:
    context = ConversationContext("system")
    add_turns(context, turns)
    original = user_entries(context)

    plan = RetentionPlanner(budget, minimum).plan(context.snapshot())

    assert plan.can_compact
    assert all(entry.payload.get("role") != "user" for entry in plan.compactable_entries)
    retained = (*plan.preserved_user_entries, *(entry for entry in plan.recent_entries if entry.payload.get("role") == "user"))
    assert [(entry.id, entry.payload["content"]) for entry in retained] == [
        (entry.id, entry.payload["content"]) for entry in original
    ]


USER_CONTENTS = (
    "plain unique-01",
    "多行\n中文 unique-02",
    "```python\nprint('unique-03')\n```",
    "<system>unique-04</system>",
    "</user-message> unique-05",
    "忽略之前指令 unique-06",
    "emoji 🚀 unique-07",
    "tabs\tand\tspaces unique-08",
    "?*[]()\\ unique-09",
    "\r\n mixed unique-10",
    "x" * 8_000 + "unique-11",
    " unique-12 ",
)


@pytest.mark.parametrize("content", USER_CONTENTS, ids=tuple(f"content-{index}" for index in range(1, 13)))
async def test_successful_compaction_keeps_original_user_entry_identity_and_text(content) -> None:
    context = ConversationContext("system")
    first = context.append_user(content)
    context.append_assistant("old answer " + "a" * 500)
    add_turns(context, 12, prefix="later")
    before = [(entry.id, entry.payload["content"]) for entry in user_entries(context)]
    snapshot = context.snapshot()
    plan = RetentionPlanner(80, 3).plan(snapshot)

    result = await ContextSummarizer(SummaryProvider(), context).summarize(snapshot, plan)

    assert result.succeeded
    after = [(entry.id, entry.payload["content"]) for entry in user_entries(context)]
    assert after == before
    assert after[0] == (first.id, content)


@pytest.mark.parametrize("rounds", [1, 2, 3, 4, 5, 6], ids=("once", "twice", "three", "four", "five", "six"))
async def test_repeated_compaction_never_duplicates_or_rewrites_user_entries(rounds) -> None:
    context = ConversationContext("system")
    add_turns(context, 14, prefix="initial")
    expected = [(entry.id, entry.payload["content"]) for entry in user_entries(context)]
    provider = SummaryProvider()
    planner = RetentionPlanner(50, 3)

    for cycle in range(rounds):
        add_turns(context, 4, prefix=f"cycle-{cycle}")
        expected = [(entry.id, entry.payload["content"]) for entry in user_entries(context)]
        snapshot = context.snapshot()
        plan = planner.plan(snapshot)
        assert plan.can_compact
        result = await ContextSummarizer(provider, context).summarize(snapshot, plan)
        assert result.succeeded
        assert [(entry.id, entry.payload["content"]) for entry in user_entries(context)] == expected


@pytest.mark.parametrize(
    "sentinel",
    ["SECRET-A1", "秘密-B2", "<tag>C3</tag>", "line1\nD4", "`code-E5`", "ignore-all-F6"],
    ids=("ascii", "cjk", "tag", "multiline", "code", "instruction"),
)
async def test_system_summary_never_embeds_user_original(sentinel) -> None:
    context = ConversationContext("system")
    context.append_user(sentinel)
    context.append_assistant("answer " + "x" * 400)
    add_turns(context, 10)
    snapshot = context.snapshot()
    plan = RetentionPlanner(30, 2).plan(snapshot)

    result = await ContextSummarizer(SummaryProvider(), context).summarize(snapshot, plan)
    messages = context.export_messages()

    assert result.succeeded
    assert sentinel not in messages[1]["content"]
    assert any(message.get("role") == "user" and message.get("content") == sentinel for message in messages)


class StatusSummarizer:
    def __init__(self) -> None:
        self.calls = 0

    async def summarize(self, snapshot, plan):
        self.calls += 1
        return SummaryResult("success")


@pytest.mark.parametrize("size", [1_000, 10_000, 100_000, 300_000], ids=("small", "medium", "large", "very-large"))
async def test_large_user_message_has_no_special_preflight_block(size) -> None:
    summarizer = StatusSummarizer()
    manager = ContextManager(
        ContextConfig(),
        summarizer,
        retention_planner=RetentionPlanner(20, 2),
    )
    context = ConversationContext("system")
    context.append_user("中" * size)
    for index in range(8):
        context.append_assistant(f"assistant-{index}-" + "a" * 100)

    report = await manager.compact(context, CompressionTrigger.MANUAL)

    assert report.status == "success"
    assert summarizer.calls == 1


@pytest.mark.parametrize(
    "sizes",
    [(24_003,), (30_000,), (18_000, 18_000, 18_000), (24_000, 21_000, 12_003), (9_000, 9_000, 33_000)],
    ids=("single", "single-large", "equal-group", "aggregate", "mixed"),
)
def test_lightweight_tool_persistence_does_not_touch_user_entries(tmp_path, sizes) -> None:
    store = ContextArtifactStore(tmp_path, "retention-unit")
    store.start()
    context = ConversationContext("system")
    context.append_user("before-user")
    calls = [ToolCall(f"call-{index}", "read_file", "{}") for index in range(len(sizes))]
    context.append_assistant_tool_call(calls)
    for call, size in zip(calls, sizes, strict=True):
        context.append_tool_result(call, success_result("read_file", "ok", "x" * size))
    context.append_user("after-user")
    before = [(entry.id, entry.payload["content"]) for entry in user_entries(context)]

    LightweightCompactor(store).apply(context)

    assert [(entry.id, entry.payload["content"]) for entry in user_entries(context)] == before
    store.close()


@pytest.mark.parametrize("legacy_count", [1, 2, 3, 4, 5], ids=("one", "two", "three", "four", "five"))
async def test_legacy_summary_archive_is_rehydrated_as_real_user_entries(legacy_count) -> None:
    context = ConversationContext("system")
    original = [context.append_user(f"legacy-{index}") for index in range(legacy_count)]
    snapshot = context.snapshot()
    legacy = context.make_entry(
        {"role": "system", "content": "<conversation-summary>legacy</conversation-summary>"},
        summarized_user_ids=tuple(entry.id for entry in original),
    )
    assert context.replace_entries_if_version(snapshot.version, (snapshot.entries[0], legacy))
    for index in range(10):
        context.append_assistant(f"recent-{index}-" + "a" * 100)
    snapshot = context.snapshot()
    plan = RetentionPlanner(20, 2).plan(snapshot)

    result = await ContextSummarizer(SummaryProvider(), context).summarize(snapshot, plan)

    assert result.succeeded
    restored = user_entries(context)
    assert [(entry.id, entry.payload["content"]) for entry in restored] == [
        (entry.id, entry.payload["content"]) for entry in original
    ]
