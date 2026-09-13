from __future__ import annotations

import asyncio
from dataclasses import replace
import os

import pytest

from artcode._session import LocalSession
from artcode._tool import LocalTools
from artcode._workspace import LocalWorkspace
from artcode.core.model import Completed, ModelMessage, ProtocolFailure, TextDelta, ToolRequest, ToolRequests
from artcode.core.session import AssistantCompletion, CompactionTrigger, SessionSelection
from artcode.core.tool import RunMode, ToolResult


class SummaryModel:
    def __init__(self, text="summary", *, failure=False, wait=False):
        self.calls = 0
        self.text = text
        self.failure = failure
        self.wait = wait
        self.started = asyncio.Event()

    async def stream(self, request):
        self.calls += 1
        self.started.set()
        if self.wait:
            await asyncio.Event().wait()
        if self.failure:
            raise ProtocolFailure("summary failure")
        yield TextDelta(self.text)
        yield Completed("stop")

    async def close(self):
        pass


async def scenario(root):
    session = LocalSession(root, SessionSelection.new(), context_window_tokens=1000, recent_fact_count=1)
    tools = replace(LocalTools().open_run(LocalWorkspace(root), RunMode.CHAT), descriptors=())
    session.commit_user("original user")
    session.commit_assistant("h" * 5000, AssistantCompletion.NATURAL)
    lease = await session.prepare_run("current goal", tools)
    request = session.dispatch_run(lease).request
    return session, tools, lease, request


@pytest.mark.parametrize("failure", [True, False])
async def test_failed_or_larger_summary_keeps_request_and_stops_same_prefix_retries(tmp_path, failure):
    session, tools, lease, request = await scenario(tmp_path)
    facts = session.snapshot().facts
    model = SummaryModel("oversized " * 1000, failure=failure)
    first = await session.prepare_next_request(lease, request, tools, model=model)
    second = await session.prepare_next_request(lease, first.request, tools, model=model)
    emergency = await session.prepare_next_request(lease, second.request, tools, model=model, trigger=CompactionTrigger.EMERGENCY)
    again = await session.prepare_next_request(lease, emergency.request, tools, model=model, trigger=CompactionTrigger.EMERGENCY)
    assert first.request == second.request == emergency.request == again.request == request
    assert not first.can_continue
    assert model.calls == 1  # The same failed prefix is never retried under another trigger.
    assert session.snapshot().facts == facts
    assert not session.snapshot().summary_active
    session.close()


async def test_cancelled_summary_keeps_request_facts_and_can_be_finished(tmp_path):
    session, tools, lease, request = await scenario(tmp_path)
    before = session.snapshot()
    model = SummaryModel(wait=True)
    task = asyncio.create_task(session.prepare_next_request(lease, request, tools, model=model))
    await model.started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    followup = await session.prepare_next_request(lease, request, tools, model=model)
    assert followup.request == request
    assert model.calls == 1
    assert session.snapshot().facts == before.facts
    assert not session.snapshot().summary_active
    session.close()


async def test_summary_save_failure_preserves_previous_saved_summary(tmp_path, monkeypatch):
    session, tools, lease, request = await scenario(tmp_path)
    # A previous summary is a derived value and must survive a failed replacement.
    initial = await session.compact(SummaryModel("previous summary"), CompactionTrigger.MANUAL)
    assert initial.status == "success"
    state_path = session.archive_path.with_name("state.json")
    saved = state_path.read_bytes()
    replace_file = os.replace
    def fail_state_replace(source, destination):
        if str(destination).endswith("state.json"):
            raise OSError("state save failed")
        return replace_file(source, destination)
    monkeypatch.setattr(os, "replace", fail_state_replace)
    before = session.snapshot().facts
    prepared = await session.prepare_next_request(lease, request, tools, model=SummaryModel())
    assert prepared.compaction.status == "failed"
    assert prepared.request == request
    assert session.snapshot().facts == before
    assert session.snapshot().summary_active
    assert state_path.read_bytes() == saved
    session.close()


async def test_prepare_run_does_not_install_a_larger_automatic_summary(tmp_path):
    session = LocalSession(tmp_path, SessionSelection.new(), context_window_tokens=50, recent_fact_count=1)
    tools = replace(LocalTools().open_run(LocalWorkspace(tmp_path), RunMode.CHAT), descriptors=())
    session.commit_user("user")
    session.commit_assistant("history", AssistantCompletion.NATURAL)
    model = SummaryModel("larger summary " * 500)
    lease = await session.prepare_run("goal", tools, model_for_compaction=model)
    assert not session.snapshot().summary_active
    assert "history" in str(lease.prompt_preview)
    assert "larger summary" not in str(lease.prompt_preview)
    dispatched = session.dispatch_run(lease)
    await session.prepare_next_request(lease, dispatched.request, tools, model=model)
    assert model.calls == 1
    session.close()


async def test_automatic_public_compaction_rejects_larger_summary(tmp_path):
    session = LocalSession(tmp_path, SessionSelection.new(), recent_fact_count=1)
    session.commit_user("user")
    session.commit_assistant("short", AssistantCompletion.NATURAL)
    session.commit_user("latest")
    before = session.snapshot().facts
    report = await session.compact(SummaryModel("long " * 100), CompactionTrigger.AUTOMATIC)
    assert report.status == "noop"
    assert not session.snapshot().summary_active
    assert session.snapshot().facts == before
    session.close()


async def test_reconstruction_rejects_uncommitted_or_partial_tool_exchange(tmp_path):
    session, tools, lease, request = await scenario(tmp_path)
    call = ToolRequest("missing-result", "read_file", "{}")
    partial = replace(request, prompt=(*request.prompt, ModelMessage("assistant", None, (call,))))
    with pytest.raises(ValueError, match="完整事实"):
        await session.prepare_next_request(lease, partial, tools, model=SummaryModel())
    assert session.dispatch_run(lease).request == request
    session.close()


async def test_repeated_failed_service_is_bounded_even_as_new_facts_arrive(tmp_path):
    session, tools, lease, request = await scenario(tmp_path)
    model = SummaryModel(failure=True)
    before = session.snapshot().facts
    for number in range(7):
        call = ToolRequest(str(number), "read_file", "{}")
        result = ToolResult(str(number), "read_file", True, "new history " * 200)
        session.commit_tool_exchange((call,), (result,))
        request = replace(request, prompt=(*request.prompt, ModelMessage("assistant", None, (call,)), ModelMessage("tool", result.content, tool_request_id=call.id)))
        prepared = await session.prepare_next_request(lease, request, tools, model=model)
        assert prepared.request == request
    assert model.calls == 3
    assert session.snapshot().facts[:len(before)] == before
    assert not session.snapshot().summary_active
    session.close()


@pytest.mark.parametrize("active_run", (False, True))
async def test_rejected_summary_closes_provider_stream_before_returning(tmp_path, active_run):
    class ToolRequestSummary:
        def __init__(self):
            self.closed = asyncio.Event()
            self.active_stream = None

        def stream(self, request):
            self.active_stream = self.events()
            return self.active_stream

        async def events(self):
            try:
                yield ToolRequests((ToolRequest("invalid-summary-tool", "read_file", "{}"),))
                await asyncio.Event().wait()
            finally:
                self.closed.set()

        async def close(self):
            pass

    session, tools, lease, request = await scenario(tmp_path)
    before = session.snapshot()
    model = ToolRequestSummary()
    try:
        if active_run:
            prepared = await session.prepare_next_request(lease, request, tools, model=model)
            report = prepared.compaction
            assert prepared.request == request
        else:
            report = await session.compact(model, CompactionTrigger.AUTOMATIC)
        assert report.status == "failed"
        assert session.snapshot() == before
        assert model.closed.is_set()
    finally:
        if model.active_stream is not None:
            await model.active_stream.aclose()
        session.close()
