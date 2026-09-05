from __future__ import annotations

import asyncio
from pathlib import Path

from artcode._agent import AgentRunner
from artcode._session import LocalSession
from artcode._tool import LocalTools
from artcode._workspace import LocalWorkspace
from artcode.core.agent import RunControl, RunFinished, StopReason, TextEvent, ToolBatchEvent
from artcode.core.model import (
    Completed,
    ModelRequest,
    ProtocolFailure,
    TextDelta,
    ToolRequest,
    ToolRequests,
    Usage,
)
from artcode.core.session import AssistantCompletion, AssistantFact, SessionSelection, ToolExchangeFact, UserFact
from artcode.core.tool import PermissionMode, RunMode


class ScriptedModel:
    def __init__(self, responses: list[list[object] | Exception]) -> None:
        self.responses = responses
        self.calls: list[ModelRequest] = []

    async def stream(self, request: ModelRequest):
        self.calls.append(request)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        for event in response:
            yield event

    async def close(self) -> None:
        return None


async def prepared(tmp_path: Path, mode: RunMode = RunMode.CHAT):
    root = tmp_path / "workspace"
    root.mkdir()
    workspace = LocalWorkspace(root)
    tools = LocalTools(permission_mode=PermissionMode.FULL)
    session = LocalSession(root, SessionSelection.new())
    lease = await session.prepare_run("goal", tools.open_run(workspace, mode))
    return workspace, tools, session, session.dispatch_run(lease)


async def collect(runner: AgentRunner, dispatched, **kwargs):
    return [event async for event in runner.run(dispatched, **kwargs)]


async def test_natural_text_stream_commits_only_on_completion(tmp_path: Path) -> None:
    _, tools, session, dispatched = await prepared(tmp_path)
    model = ScriptedModel([[TextDelta("hel"), TextDelta("lo"), Usage(3, 2, 5), Completed("stop")]])

    events = await collect(AgentRunner(model, tools, session), dispatched)

    assert [event.text for event in events if isinstance(event, TextEvent)] == ["hel", "lo"]
    finished = next(event for event in events if isinstance(event, RunFinished))
    assert finished.outcome.stop_reason is StopReason.NATURAL
    assert finished.outcome.usage == Usage(3, 2, 5)
    assert session.snapshot().facts == (
        UserFact("goal"),
        AssistantFact("hello", AssistantCompletion.NATURAL),
    )
    session.close()


async def test_length_end_keeps_visible_text_with_distinct_reason(tmp_path: Path) -> None:
    _, tools, session, dispatched = await prepared(tmp_path)
    model = ScriptedModel([[TextDelta("partial but valid"), Completed("length")]])

    events = await collect(AgentRunner(model, tools, session), dispatched)

    outcome = next(item.outcome for item in events if isinstance(item, RunFinished))
    assert outcome.stop_reason is StopReason.LENGTH
    assert session.snapshot().facts[-1] == AssistantFact("partial but valid", AssistantCompletion.LENGTH)
    session.close()


async def test_complete_tool_batch_is_committed_and_protocol_continues(tmp_path: Path) -> None:
    workspace, tools, session, dispatched = await prepared(tmp_path)
    (workspace.root / "a.txt").write_text("A", encoding="utf-8")
    (workspace.root / "b.txt").write_text("B", encoding="utf-8")
    requests = (
        ToolRequest("a", "read_file", '{"path":"a.txt"}'),
        ToolRequest("b", "read_file", '{"path":"b.txt"}'),
    )
    model = ScriptedModel(
        [
            [TextDelta("checking"), ToolRequests(requests), Completed("tool_calls"), Usage(2, 1, 3)],
            [TextDelta("AB"), Usage(4, 2, 6), Completed("stop")],
        ]
    )

    events = await collect(AgentRunner(model, tools, session), dispatched)

    exchange = next(fact for fact in session.snapshot().facts if isinstance(fact, ToolExchangeFact))
    assert exchange.assistant_text == "checking"
    assert [item.call_id for item in exchange.results] == ["a", "b"]
    assert [item.content for item in exchange.results] == ["A", "B"]
    assert model.calls[1].prompt[-3].tool_requests == requests
    assert [item.tool_request_id for item in model.calls[1].prompt[-2:]] == ["a", "b"]
    outcome = next(item.outcome for item in events if isinstance(item, RunFinished))
    assert outcome.usage == Usage(6, 3, 9)
    session.close()


async def test_ordinary_run_has_no_product_round_limit(tmp_path: Path) -> None:
    workspace, tools, session, dispatched = await prepared(tmp_path)
    (workspace.root / "x.txt").write_text("x", encoding="utf-8")
    tool_response = [
        ToolRequests((ToolRequest("call", "read_file", '{"path":"x.txt"}'),)),
        Completed("tool_calls"),
    ]
    model = ScriptedModel([list(tool_response) for _ in range(55)] + [[TextDelta("done"), Completed("stop")]])

    events = await collect(AgentRunner(model, tools, session), dispatched)

    outcome = next(item.outcome for item in events if isinstance(item, RunFinished))
    assert outcome.stop_reason is StopReason.NATURAL
    assert outcome.rounds == 56
    assert len(model.calls) == 56
    session.close()


async def test_explicit_round_limit_is_distinct_and_stops_after_closed_exchange(tmp_path: Path) -> None:
    workspace, tools, session, dispatched = await prepared(tmp_path)
    (workspace.root / "x.txt").write_text("x", encoding="utf-8")
    response = [ToolRequests((ToolRequest("call", "read_file", '{"path":"x.txt"}'),)), Completed("tool_calls")]
    model = ScriptedModel([list(response), list(response), list(response)])

    events = await collect(AgentRunner(model, tools, session), dispatched, max_rounds=2)

    outcome = next(item.outcome for item in events if isinstance(item, RunFinished))
    assert outcome.stop_reason is StopReason.LIMIT
    assert outcome.rounds == 2
    assert len(model.calls) == 2
    assert all(isinstance(fact, (UserFact, ToolExchangeFact)) for fact in session.snapshot().facts)
    session.close()


async def test_model_failure_keeps_temporary_text_visible_but_out_of_transcript(tmp_path: Path) -> None:
    _, tools, session, dispatched = await prepared(tmp_path)

    class PartialFailure(ScriptedModel):
        async def stream(self, request: ModelRequest):
            self.calls.append(request)
            yield TextDelta("visible temporary")
            raise ProtocolFailure("dropped")

    events = await collect(AgentRunner(PartialFailure([]), tools, session), dispatched)

    assert any(isinstance(item, TextEvent) and item.text == "visible temporary" for item in events)
    outcome = next(item.outcome for item in events if isinstance(item, RunFinished))
    assert outcome.stop_reason is StopReason.MODEL_FAILURE
    assert session.snapshot().facts == (UserFact("goal"),)
    session.close()


async def test_controlled_cancel_interrupts_blocked_model_and_commits_no_assistant(tmp_path: Path) -> None:
    _, tools, session, dispatched = await prepared(tmp_path)

    class BlockingModel:
        def __init__(self) -> None:
            self.started = asyncio.Event()

        async def stream(self, request: ModelRequest):
            self.started.set()
            await asyncio.Event().wait()
            yield  # pragma: no cover

        async def close(self):
            return None

    model = BlockingModel()
    control = RunControl()
    task = asyncio.create_task(collect(AgentRunner(model, tools, session), dispatched, control=control))
    await model.started.wait()
    control.cancel()
    events = await asyncio.wait_for(task, 1)

    outcome = next(item.outcome for item in events if isinstance(item, RunFinished))
    assert outcome.stop_reason is StopReason.CANCELLED
    assert session.snapshot().facts == (UserFact("goal"),)
    session.close()
