from __future__ import annotations

import json
from pathlib import Path

import httpx

from artcode._agent import AgentRunner
from artcode._model import DeepSeekModel
from artcode._session import LocalSession
from artcode._tool import LocalTools
from artcode._workspace import LocalWorkspace
from artcode.core.agent import RunFinished, StopReason
from artcode.core.model import ModelSettings
from artcode.core.session import AssistantFact, SessionSelection, ToolExchangeFact
from artcode.core.tool import PermissionMode, RunMode


async def test_session_agent_model_tool_workspace_real_flow(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "note.txt").write_text("INTEGRATION", encoding="utf-8")
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        payload = json.loads(request.content)
        if requests == 1:
            assert payload["messages"][-1]["content"] == "read it"
            body = (
                b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"c1","function":{"name":"read_file","arguments":"{\\"path\\":\\"note.txt\\"}"}}]},"finish_reason":"tool_calls"}]}\n\n'
                b'data: [DONE]\n\n'
            )
        else:
            assert payload["messages"][-1]["role"] == "tool"
            body = (
                b'data: {"choices":[{"delta":{"content":"INTEGRATION"},"finish_reason":"stop"}]}\n\n'
                b'data: [DONE]\n\n'
            )
        return httpx.Response(200, content=body)

    workspace = LocalWorkspace(root)
    tools = LocalTools(permission_mode=PermissionMode.FULL)
    session = LocalSession(root, SessionSelection.new())
    lease = await session.prepare_run("read it", tools.open_run(workspace, RunMode.CHAT))
    model = DeepSeekModel(
        ModelSettings("deepseek-chat", "https://model.example/v1", "secret"),
        transport=httpx.MockTransport(handler),
    )
    events = [item async for item in AgentRunner(model, tools, session).run(session.dispatch_run(lease))]

    assert requests == 2
    assert any(isinstance(item, ToolExchangeFact) for item in session.snapshot().facts)
    assert isinstance(session.snapshot().facts[-1], AssistantFact)
    assert next(item.outcome for item in events if isinstance(item, RunFinished)).stop_reason is StopReason.NATURAL
    await model.close()
    session.close()
