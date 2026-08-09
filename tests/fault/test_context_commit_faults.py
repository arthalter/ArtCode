from __future__ import annotations

import asyncio

import pytest

from artcode.context_management import ContextArtifactStore, ContextSummarizer, LightweightCompactor
from artcode.context_management.retention import RetentionPlanner
from artcode.context_management.summarizer import SUMMARY_TITLES, VERBATIM_PLACEHOLDER
from artcode.conversation import ConversationContext
from artcode.errors import NetworkError
from artcode.providers.events import content_delta_event, done_event
from artcode.providers.tool_calls import ToolCall
from artcode.tools import success_result

pytestmark = [pytest.mark.ch10_5, pytest.mark.fault]


def valid_summary() -> str:
    sections = [
        f"## {index}. {title}\n{VERBATIM_PLACEHOLDER if index == 6 else 'internal'}"
        for index, title in enumerate(SUMMARY_TITLES, start=1)
    ]
    return "<analysis>draft</analysis><summary>" + "\n\n".join(sections) + "</summary>"


def compressible():
    context = ConversationContext("fixed")
    for index in range(12):
        context.append_user(f"user-{index}")
        context.append_assistant("answer" * 50)
    snapshot = context.snapshot()
    return context, snapshot, RetentionPlanner(1, 2).plan(snapshot)


async def test_provider_failure_preserves_exact_conversation_snapshot() -> None:
    class FailedProvider:
        async def stream_chat(self, messages, tools=None, *, options=None):
            raise NetworkError("failed", "retry")
            yield

    context, snapshot, plan = compressible()
    before = context.snapshot()

    result = await ContextSummarizer(FailedProvider(), context).summarize(snapshot, plan)

    assert result.status == "failed"
    assert context.snapshot() == before


async def test_parser_failure_preserves_exact_conversation_snapshot() -> None:
    class InvalidProvider:
        async def stream_chat(self, messages, tools=None, *, options=None):
            yield content_delta_event("not a summary")
            yield done_event()

    context, snapshot, plan = compressible()
    before = context.snapshot()

    result = await ContextSummarizer(InvalidProvider(), context).summarize(snapshot, plan)

    assert result.status == "failed"
    assert context.snapshot() == before


async def test_concurrent_version_change_rejects_summary_commit_without_lost_entry() -> None:
    context, snapshot, plan = compressible()

    class MutatingProvider:
        async def stream_chat(self, messages, tools=None, *, options=None):
            context.append_user("concurrent-user")
            yield content_delta_event(valid_summary())
            yield done_event()

    result = await ContextSummarizer(MutatingProvider(), context).summarize(snapshot, plan)

    assert result.status == "failed"
    assert context.export_messages()[-1] == {"role": "user", "content": "concurrent-user"}


async def test_summary_cancellation_propagates_and_preserves_snapshot() -> None:
    gate = asyncio.Event()

    class BlockingProvider:
        async def stream_chat(self, messages, tools=None, *, options=None):
            await gate.wait()
            yield content_delta_event(valid_summary())

    context, snapshot, plan = compressible()
    before = context.snapshot()
    task = asyncio.create_task(ContextSummarizer(BlockingProvider(), context).summarize(snapshot, plan))
    await asyncio.sleep(0)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert context.snapshot() == before


def test_artifact_is_removed_when_conversation_marker_commit_fails(tmp_path, monkeypatch) -> None:
    store = ContextArtifactStore(tmp_path, "commit-fault")
    store.start()
    context = ConversationContext("fixed")
    call = ToolCall("call", "read_file", "{}")
    context.append_assistant_tool_call((call,))
    context.append_tool_result(call, success_result("read_file", "ok", "x" * 30_000))
    before = context.snapshot()
    monkeypatch.setattr(context, "replace_entry_content", lambda *args, **kwargs: False)

    report = LightweightCompactor(store).apply(context)

    assert report.persisted_count == 0
    assert context.snapshot() == before
    assert not list(store.tool_results_dir.glob("*.txt"))
    store.close()
