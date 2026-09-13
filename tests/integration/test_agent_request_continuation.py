from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from artcode._agent import AgentRunner
from artcode._session import LocalSession
from artcode._tool import LocalTools
from artcode._workspace import LocalWorkspace
from artcode.core.agent import RunControl, RunFinished, StopReason, ToolBatchEvent
from artcode.core.model import AuthenticationFailure, Completed, ContextWindowFailure, ModelFailure, NetworkFailure, TextDelta, ToolRequest, ToolRequests
from artcode.core.session import AssistantCompletion, SessionSelection, ToolExchangeFact, UserFact
from artcode.core.tool import PermissionMode, RunMode


class ContextFailureModel:
    def __init__(self, *, failures: int = 1, failure_type: type[ModelFailure] = ContextWindowFailure, hold_summary: bool = False):
        self.calls = 0
        self.summaries = 0
        self.failures = failures
        self.failure_type = failure_type
        self.hold_summary = hold_summary
        self.summary_started = asyncio.Event()
        self.summary_closed = asyncio.Event()

    async def stream(self, request):
        system = "\n".join(item.content or "" for item in request.prompt if item.role == "system")
        if "Summarize only" in system:
            self.summaries += 1
            self.summary_started.set()
            try:
                if self.hold_summary:
                    await asyncio.Event().wait()
                yield TextDelta("Earlier work is complete.")
                yield Completed("stop")
            finally:
                self.summary_closed.set()
            return
        self.calls += 1
        if self.calls == 1:
            yield ToolRequests((ToolRequest("write-once", "write_file", json.dumps({
                "path": "created.txt", "content": "created exactly once",
            })),))
            yield Completed("tool_calls")
            return
        if self.calls <= self.failures + 1:
            raise self.failure_type("controlled provider failure")
        assert request.prompt[-1].tool_request_id == "write-once"
        assert "已写入" in request.prompt[-1].content
        yield TextDelta("finished")
        yield Completed("stop")

    async def close(self):
        pass


async def setup_run(tmp_path: Path):
    workspace = LocalWorkspace(tmp_path)
    tools = LocalTools(permission_mode=PermissionMode.FULL)
    session = LocalSession(tmp_path, SessionSelection.new(), user_home=tmp_path / "home")
    for index in range(10):
        session.commit_user(f"earlier goal {index}")
        session.commit_assistant("historical details " * 150, AssistantCompletion.NATURAL)
    lease = await session.prepare_run("current goal", tools.open_run(workspace, RunMode.ACT))
    return workspace, tools, session, session.dispatch_run(lease)


@pytest.mark.parametrize("failures,failure_type,expected_calls,expected_summaries,reason", [
    (1, ContextWindowFailure, 3, 1, StopReason.NATURAL),
    (2, ContextWindowFailure, 3, 1, StopReason.MODEL_FAILURE),
    (1, NetworkFailure, 2, 0, StopReason.MODEL_FAILURE),
    (1, AuthenticationFailure, 2, 0, StopReason.MODEL_FAILURE),
])
async def test_context_recovery_is_bounded_and_never_replays_a_completed_tool(
    tmp_path: Path, failures: int, failure_type: type[ModelFailure], expected_calls: int,
    expected_summaries: int, reason: StopReason,
) -> None:
    workspace, tools, session, dispatched = await setup_run(tmp_path)
    model = ContextFailureModel(failures=failures, failure_type=failure_type)
    before_users = [fact.text for fact in session.snapshot().facts if isinstance(fact, UserFact)]
    try:
        events = [event async for event in AgentRunner(model, tools, session).run(dispatched)]
        final = next(event.outcome for event in reversed(events) if isinstance(event, RunFinished))
        assert final.stop_reason is reason
        assert final.rounds == expected_calls == model.calls
        assert model.summaries == expected_summaries
        exchanges = [fact for fact in session.snapshot().facts if isinstance(fact, ToolExchangeFact)]
        assert len(exchanges) == 1 and exchanges[0].results[0].ok
        assert (tmp_path / "created.txt").read_text() == "created exactly once"
        assert [fact.text for fact in session.snapshot().facts if isinstance(fact, UserFact)] == before_users
    finally:
        await session.aclose()
        await tools.close()
        await workspace.aclose()


async def test_round_limit_prevents_an_extra_summary_or_model_attempt(tmp_path: Path) -> None:
    workspace, tools, session, dispatched = await setup_run(tmp_path)
    model = ContextFailureModel()
    try:
        events = [event async for event in AgentRunner(model, tools, session).run(dispatched, max_rounds=2)]
        assert events[-1].outcome.stop_reason is StopReason.MODEL_FAILURE
        assert model.calls == 2 and model.summaries == 0
    finally:
        await session.aclose()
        await tools.close()
        await workspace.aclose()


async def test_cancel_during_summary_does_not_commit_the_tool_exchange_twice(tmp_path: Path) -> None:
    workspace, tools, session, dispatched = await setup_run(tmp_path)
    model = ContextFailureModel(hold_summary=True)
    control = RunControl()

    async def collect():
        return [event async for event in AgentRunner(model, tools, session).run(dispatched, control=control)]

    task = asyncio.create_task(collect())
    try:
        await asyncio.wait_for(model.summary_started.wait(), 1)
        control.cancel()
        events = await asyncio.wait_for(task, 1)
        assert events[-1].outcome.stop_reason is StopReason.CANCELLED
        assert len([event for event in events if isinstance(event, RunFinished)]) == 1
        assert model.summary_closed.is_set()
        exchanges = [fact for fact in session.snapshot().facts if isinstance(fact, ToolExchangeFact)]
        assert len(exchanges) == 1 and exchanges[0].results[0].ok
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await session.aclose()
        await tools.close()
        await workspace.aclose()


@pytest.mark.parametrize("max_rounds", (None, 1))
async def test_cancel_at_completed_batch_keeps_successful_write_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, max_rounds: int | None,
) -> None:
    workspace, tools, session, dispatched = await setup_run(tmp_path)
    model = ContextFailureModel()
    control = RunControl()
    execute_batch = tools.execute_batch

    async def cancel_after_success(*args, **kwargs):
        results = await execute_batch(*args, **kwargs)
        control.cancel()
        return results

    monkeypatch.setattr(tools, "execute_batch", cancel_after_success)
    try:
        events = [event async for event in AgentRunner(model, tools, session).run(
            dispatched, control=control, max_rounds=max_rounds,
        )]
        assert events[-1].outcome.stop_reason is StopReason.CANCELLED
        assert model.calls == 1
        assert (tmp_path / "created.txt").read_text() == "created exactly once"
        exchanges = [fact for fact in session.snapshot().facts if isinstance(fact, ToolExchangeFact)]
        assert len(exchanges) == 1
        assert exchanges[0].results[0].ok
        assert exchanges[0].results[0].error_code is None
        batches = [event for event in events if isinstance(event, ToolBatchEvent)]
        assert len(batches) == 1 and batches[0].results == exchanges[0].results
    finally:
        await session.aclose()
        await tools.close()
        await workspace.aclose()


async def test_cancel_at_stream_close_does_not_commit_temporary_text(tmp_path: Path) -> None:
    workspace, tools, session, dispatched = await setup_run(tmp_path)
    control = RunControl()
    before = session.snapshot().facts

    class CancelOnCloseModel:
        async def stream(self, request):
            yield TextDelta("temporary answer")
            yield Completed("stop")
            control.cancel()

        async def close(self):
            pass

    try:
        events = [event async for event in AgentRunner(CancelOnCloseModel(), tools, session).run(
            dispatched, control=control,
        )]
        assert events[-1].outcome.stop_reason is StopReason.CANCELLED
        assert session.snapshot().facts == before
    finally:
        await session.aclose()
        await tools.close()
        await workspace.aclose()
