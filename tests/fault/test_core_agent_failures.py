from __future__ import annotations

from pathlib import Path

from artcode._agent import AgentRunner
from artcode._session import LocalSession
from artcode._tool import LocalTools
from artcode._workspace import LocalWorkspace
from artcode.core.agent import RunFinished, StopReason
from artcode.core.model import Completed, ModelRequest, TextDelta, ToolRequest, ToolRequests
from artcode.core.session import AssistantFact, SessionSelection, ToolExchangeFact
from artcode.core.tool import PermissionMode, RunMode


class RecoveringModel:
    def __init__(self) -> None:
        self.calls = 0

    async def stream(self, request: ModelRequest):
        self.calls += 1
        if self.calls == 1:
            yield ToolRequests((ToolRequest("x", "missing_tool", "{}"),))
            yield Completed("tool_calls")
        else:
            assert request.prompt[-1].content
            yield TextDelta("recovered")
            yield Completed("stop")

    async def close(self):
        return None


async def test_local_tool_failure_returns_to_model_and_run_continues(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    workspace = LocalWorkspace(root)
    tools = LocalTools(permission_mode=PermissionMode.FULL)
    session = LocalSession(root, SessionSelection.new())
    lease = await session.prepare_run("goal", tools.open_run(workspace, RunMode.CHAT))

    events = [item async for item in AgentRunner(RecoveringModel(), tools, session).run(session.dispatch_run(lease))]

    exchange = next(item for item in session.snapshot().facts if isinstance(item, ToolExchangeFact))
    assert exchange.results[0].error_code == "tool_not_found"
    assert isinstance(session.snapshot().facts[-1], AssistantFact)
    assert next(item.outcome for item in events if isinstance(item, RunFinished)).stop_reason is StopReason.NATURAL
    session.close()


class OddFinishModel:
    async def stream(self, request: ModelRequest):
        yield TextDelta("temporary")
        yield Completed("content_filter")

    async def close(self):
        return None


async def test_unusable_finish_reason_is_distinct_and_does_not_commit_temporary_text(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    workspace = LocalWorkspace(root)
    tools = LocalTools()
    session = LocalSession(root, SessionSelection.new())
    lease = await session.prepare_run("goal", tools.open_run(workspace, RunMode.CHAT))
    events = [item async for item in AgentRunner(OddFinishModel(), tools, session).run(session.dispatch_run(lease))]

    outcome = next(item.outcome for item in events if isinstance(item, RunFinished))
    assert outcome.stop_reason is StopReason.CANNOT_CONTINUE
    assert len(session.snapshot().facts) == 1
    session.close()
