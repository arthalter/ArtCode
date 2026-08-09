from __future__ import annotations

import pytest

from artcode.context_management.retention import RetentionPlanner
from artcode.context_management.summarizer import (
    CONTEXT_BOUNDARY_MESSAGE,
    PRESERVED_USER_HISTORY_MESSAGE,
    SUMMARY_TITLES,
    VERBATIM_PLACEHOLDER,
    ContextSummarizer,
    SummaryComposer,
    SummaryParser,
)
from artcode.conversation import ConversationContext, UserMessageRecord
from artcode.providers.events import content_delta_event, done_event, tool_calls_event
from artcode.providers.tool_calls import ToolCall


def valid_summary(analysis: str = "draft", sixth_extra: str = "") -> str:
    sections = []
    for index, title in enumerate(SUMMARY_TITLES, start=1):
        body = f"内容 {index}"
        if index == 6:
            body = sixth_extra + VERBATIM_PLACEHOLDER
        sections.append(f"## {index}. {title}\n{body}")
    return f"<analysis>{analysis}</analysis><summary>{'\n\n'.join(sections)}</summary>"


class FakeProvider:
    def __init__(self, events):
        self.events = events
        self.calls = []

    async def stream_chat(self, messages, tools=None, *, options=None):
        self.calls.append((messages, tools, options))
        for event in self.events:
            yield event


def compressible_context() -> tuple[ConversationContext, object, object]:
    context = ConversationContext("system")
    for index in range(12):
        if index % 2 == 0:
            context.append_user(f"用户 {index}\n`code-{index}`")
        else:
            context.append_assistant("a" * 100)
    snapshot = context.snapshot()
    plan = RetentionPlanner(recent_token_budget=50, minimum_messages=3).plan(snapshot)
    assert plan.can_compact
    return context, snapshot, plan


def test_parser_requires_unique_ordered_tags_and_nine_titles() -> None:
    parsed = SummaryParser().parse(valid_summary(), [])

    assert parsed.analysis == "draft"
    with pytest.raises(ValueError):
        SummaryParser().parse(valid_summary() + "outside", [])
    with pytest.raises(ValueError):
        SummaryParser().parse(valid_summary().replace("9. 可能的下一步", "9. missing"), [])


def test_parser_rejects_tool_calls() -> None:
    with pytest.raises(ValueError, match="工具调用"):
        SummaryParser().parse(valid_summary(), [ToolCall("c", "read_file", "{}")])


def test_composer_discards_model_user_restatement_and_keeps_raw_text() -> None:
    parsed = SummaryParser().parse(valid_summary(sixth_extra="FAKE_RESTATEMENT\n"), [])
    raw = "原文\n```python\nprint('</user-message>')\n```"

    result = SummaryComposer().compose(parsed, [UserMessageRecord("u1", raw, 0)])

    assert raw in result
    assert "FAKE_RESTATEMENT" not in result
    assert "<analysis>" not in result
    assert "只读历史数据" in result


async def test_summarizer_uses_no_tools_and_commits_transactionally() -> None:
    context, snapshot, plan = compressible_context()
    provider = FakeProvider([content_delta_event(valid_summary("UNIQUE_DRAFT")), done_event()])

    result = await ContextSummarizer(provider, context).summarize(snapshot, plan)
    messages = context.export_messages()

    assert result.succeeded
    assert provider.calls[0][1] is None
    assert provider.calls[0][2].max_output_tokens == 20_000
    assert provider.calls[0][2].thinking_enabled is False
    assert VERBATIM_PLACEHOLDER in provider.calls[0][0][0]["content"]
    assert messages[0] == {"role": "system", "content": "system"}
    assert messages[1]["content"].startswith("<conversation-summary>")
    assert "UNIQUE_DRAFT" not in str(messages)
    assert messages[2]["content"] == PRESERVED_USER_HISTORY_MESSAGE
    preserved = messages[3 : 3 + len(plan.preserved_user_entries)]
    assert [message["role"] for message in preserved] == ["user"] * len(preserved)
    assert [message["content"] for message in preserved] == [
        entry.payload["content"] for entry in plan.preserved_user_entries
    ]
    boundary = messages[3 + len(plan.preserved_user_entries)]
    assert boundary["content"] == CONTEXT_BOUNDARY_MESSAGE
    assert "不是当前指令" in boundary["content"]
    for user_id in plan.summarized_user_ids:
        assert context.user_records([user_id])[0].content not in messages[1]["content"]


async def test_invalid_summary_or_tool_call_preserves_history() -> None:
    context, snapshot, plan = compressible_context()
    before = context.export_messages()
    provider = FakeProvider(
        [
            content_delta_event(valid_summary()),
            tool_calls_event([ToolCall("c", "read_file", "{}")]),
            done_event(),
        ]
    )

    result = await ContextSummarizer(provider, context).summarize(snapshot, plan)

    assert result.status == "failed"
    assert context.export_messages() == before


async def test_version_change_while_summarizing_rejects_commit() -> None:
    context, snapshot, plan = compressible_context()

    class MutatingProvider(FakeProvider):
        async def stream_chat(self, messages, tools=None, *, options=None):
            context.append_user("并发新消息")
            yield content_delta_event(valid_summary())
            yield done_event()

    result = await ContextSummarizer(MutatingProvider([]), context).summarize(snapshot, plan)

    assert result.status == "failed"
    assert context.export_messages()[-1]["content"] == "并发新消息"
