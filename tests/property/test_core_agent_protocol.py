from __future__ import annotations

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory

from hypothesis import given, settings, strategies as st

from artcode._agent import AgentRunner
from artcode._session import LocalSession
from artcode._tool import LocalTools
from artcode._workspace import LocalWorkspace
from artcode.core.model import Completed, ModelRequest, TextDelta, ToolRequest, ToolRequests
from artcode.core.session import SessionSelection, ToolExchangeFact
from artcode.core.tool import PermissionMode, RunMode


class Model:
    def __init__(self, requests):
        self.requests = requests
        self.calls = 0

    async def stream(self, request: ModelRequest):
        self.calls += 1
        if self.calls == 1:
            yield ToolRequests(self.requests)
            yield Completed("tool_calls")
        else:
            yield TextDelta("done")
            yield Completed("stop")

    async def close(self):
        return None


@given(st.integers(min_value=1, max_value=8))
@settings(max_examples=20)
def test_every_requested_tool_has_one_ordered_result(count: int) -> None:
    async def scenario() -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            workspace = LocalWorkspace(root)
            for index in range(count):
                (root / f"{index}.txt").write_text(str(index), encoding="utf-8")
            tools = LocalTools(permission_mode=PermissionMode.FULL)
            session = LocalSession(root, SessionSelection.new())
            lease = await session.prepare_run("goal", tools.open_run(workspace, RunMode.CHAT))
            requests = tuple(
                ToolRequest(f"c{index}", "read_file", f'{{"path":"{index}.txt"}}')
                for index in range(count)
            )
            events = [
                item
                async for item in AgentRunner(Model(requests), tools, session).run(session.dispatch_run(lease))
            ]
            exchange = next(item for item in session.snapshot().facts if isinstance(item, ToolExchangeFact))
            assert [item.id for item in exchange.requests] == [item.call_id for item in exchange.results]
            assert len(exchange.results) == count
            session.close()

    asyncio.run(scenario())
