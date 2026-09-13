from __future__ import annotations

from pathlib import Path

import pytest

from artcode._session import LocalSession
from artcode._tool import LocalTools
from artcode._workspace import LocalWorkspace
from artcode.core.model import Usage
from artcode.core.session import SessionSelection
from artcode.core.tool import RunMode
from tests.contracts.test_mcp_activation_flow import start_lazy


class NoSummary:
    async def stream(self, request):
        raise AssertionError("An empty Run has no history to summarize")
        yield  # pragma: no cover


@pytest.mark.parametrize("usage", (None, Usage(150)))
async def test_new_mcp_schema_alone_can_exhaust_next_request_budget(
    tmp_path: Path, usage: Usage | None,
) -> None:
    workspace = LocalWorkspace(tmp_path)
    tools = LocalTools()
    await start_lazy(tools, workspace)
    session = LocalSession(
        tmp_path, SessionSelection.new(), context_window_tokens=170,
    )
    try:
        original = tools.open_run(
            workspace,
            RunMode.CHAT,
            allowed_tools=frozenset({"mcp_search_tools", "mcp__local__echo"}),
        )
        lease = await session.prepare_run("echo", original)
        request = session.dispatch_run(lease).request
        before = await session.prepare_next_request(
            lease, request, original, model=NoSummary(), usage=usage,
        )
        assert before.can_continue
        assert before.budget.tokens < 170
        facts = session.snapshot().facts

        # No new arguments, result, metadata, or history can mask omitted schema tokens.
        assert tools.activate_mcp("mcp__local__echo")
        refreshed = tools.refresh_run(original)
        after = await session.prepare_next_request(
            lease, before.request, refreshed, model=NoSummary(), usage=usage,
        )

        assert after.request.prompt == before.request.prompt
        assert session.snapshot().facts == facts
        assert {item.name for item in before.request.tools} == {"mcp_search_tools"}
        assert {item.name for item in after.request.tools} == {
            "mcp_search_tools", "mcp__local__echo",
        }
        assert after.budget.tokens > before.budget.tokens
        assert after.budget.tokens >= 170
        assert not after.can_continue
        assert after.compaction is not None and after.compaction.status == "noop"
    finally:
        session.close()
        await tools.close()
