from __future__ import annotations

import pytest

from artcode.config import ContextConfig
from artcode.context_management import ContextArtifactStore, ContextManager, ContextSummarizer, LightweightCompactor
from artcode.context_management.models import CompressionTrigger
from artcode.context_management.retention import RetentionPlanner
from artcode.context_management.summarizer import SUMMARY_TITLES, VERBATIM_PLACEHOLDER
from artcode.conversation import ConversationContext
from artcode.providers.events import content_delta_event, done_event
from artcode.providers.tool_calls import ToolCall
from artcode.tools import success_result

pytestmark = pytest.mark.ch10_5


def valid_summary() -> str:
    sections = [
        f"## {index}. {title}\n{VERBATIM_PLACEHOLDER if index == 6 else f'summary-{index}'}"
        for index, title in enumerate(SUMMARY_TITLES, start=1)
    ]
    return "<analysis>draft</analysis><summary>" + "\n\n".join(sections) + "</summary>"


class Provider:
    def __init__(self) -> None:
        self.calls = 0

    async def stream_chat(self, messages, tools=None, *, options=None):
        self.calls += 1
        yield content_delta_event(valid_summary())
        yield done_event()


def user_state(context):
    return [
        (entry.id, entry.payload["content"])
        for entry in context.snapshot().entries
        if entry.payload.get("role") == "user"
    ]


def append_scenario(context, style, count=12):
    for index in range(count):
        content = f"user-{index}"
        if style == "unicode":
            content = f"用户原文-{index}-🚀"
        elif style == "multiline":
            content = f"line-{index}\n```code```"
        context.append_user(content)
        if style == "tools":
            call = ToolCall(f"call-{index}", "read_file", "{}")
            context.append_assistant_tool_call((call,), reasoning_content="reasoning")
            context.append_tool_result(call, success_result("read_file", "ok", f"value-{index}"))
        elif style == "systems":
            entry = context.make_entry({"role": "system", "content": f"internal-{index}"})
            snapshot = context.snapshot()
            context.replace_entries_if_version(snapshot.version, (*snapshot.entries, entry))
            context.append_assistant("answer" * 40)
        else:
            context.append_assistant("answer" * 40)


@pytest.mark.parametrize(
    "style",
    ["plain", "unicode", "multiline", "tools", "systems"],
    ids=("plain", "unicode", "multiline", "tools", "systems"),
)
async def test_real_summary_flow_preserves_user_state_across_history_shapes(style) -> None:
    context = ConversationContext("fixed")
    append_scenario(context, style)
    before = user_state(context)
    provider = Provider()
    manager = ContextManager(
        ContextConfig(),
        ContextSummarizer(provider, context),
        retention_planner=RetentionPlanner(20, 3),
    )

    report = await manager.compact(context, CompressionTrigger.MANUAL)

    assert report.status == "success"
    assert user_state(context) == before
    assert provider.calls == 1


@pytest.mark.parametrize("cycles", [1, 2, 3, 4, 5], ids=("one", "two", "three", "four", "five"))
async def test_multi_cycle_manager_compaction_preserves_all_user_entries(cycles) -> None:
    context = ConversationContext("fixed")
    provider = Provider()
    manager = ContextManager(
        ContextConfig(),
        ContextSummarizer(provider, context),
        retention_planner=RetentionPlanner(20, 3),
    )
    for cycle in range(cycles):
        append_scenario(context, "plain", count=6)
        before = user_state(context)
        report = await manager.compact(context, CompressionTrigger.MANUAL)
        assert report.status == "success"
        assert user_state(context) == before

    assert provider.calls == cycles


@pytest.mark.parametrize(
    "trigger",
    [CompressionTrigger.AUTOMATIC, CompressionTrigger.FORCED, CompressionTrigger.EMERGENCY],
    ids=("automatic", "forced", "emergency"),
)
async def test_every_runtime_compression_trigger_uses_same_user_preservation(trigger) -> None:
    context = ConversationContext("fixed")
    append_scenario(context, "unicode")
    before = user_state(context)
    manager = ContextManager(
        ContextConfig(),
        ContextSummarizer(Provider(), context),
        retention_planner=RetentionPlanner(20, 3),
    )

    report = await manager.compact(context, trigger)

    assert report.status == "success"
    assert user_state(context) == before


@pytest.mark.parametrize("sizes", [(30_000,), (18_000, 18_000, 18_000)], ids=("single-large", "aggregate"))
async def test_lightweight_then_heavy_compaction_is_atomic_for_users(tmp_path, sizes) -> None:
    context = ConversationContext("fixed")
    append_scenario(context, "plain", count=8)
    calls = [ToolCall(f"large-{index}", "read_file", "{}") for index in range(len(sizes))]
    context.append_assistant_tool_call(calls)
    for call, size in zip(calls, sizes, strict=True):
        context.append_tool_result(call, success_result("read_file", "ok", "x" * size))
    context.append_user("after-tool-user")
    context.append_assistant("after-tool-answer" * 40)
    before = user_state(context)
    store = ContextArtifactStore(tmp_path, "combined-flow")
    store.start()
    manager = ContextManager(
        ContextConfig(),
        ContextSummarizer(Provider(), context),
        lightweight_compactor=LightweightCompactor(store),
        retention_planner=RetentionPlanner(20, 3),
    )

    light = manager.run_lightweight(context)
    report = await manager.compact(context, CompressionTrigger.MANUAL)

    assert light.persisted_count >= 1
    assert report.status == "success"
    assert user_state(context) == before
    store.close()
