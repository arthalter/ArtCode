from __future__ import annotations

import json
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest

from artcode.agent import AgentLoop, AgentRunRequest, NORMAL_AGENT_MODE, PLAN_MODE
from artcode.agent.tools import ToolBatchExecutor
from artcode.conversation import ConversationContext
from artcode.mcp.config import load_mcp_configuration
from artcode.mcp.manager import McpManager
from artcode.mcp.adapter import create_adapter
from artcode.permissions import PermissionState
from artcode.permissions.service import PermissionService
from artcode.providers.events import content_delta_event, done_event, tool_calls_event
from artcode.providers.tool_calls import ToolCall
from artcode.tools import AllowedPathPolicy, ToolExecutionContext, create_default_tool_registry
from artcode.tools.execution import ToolExecutionService


class Approver:
    def __init__(self) -> None:
        self.count = 0

    async def request_mcp_approval(self, preview, plan_mode: bool) -> bool:
        self.count += 1
        return True


class Provider:
    def __init__(self, tool_name: str) -> None:
        self.tool_name = tool_name
        self.messages = []
        self.turn = 0

    async def stream_chat(self, messages, tools=None):
        self.messages.append(messages)
        self.turn += 1
        if self.turn == 1:
            yield tool_calls_event([ToolCall("mcp-call-1", self.tool_name, '{"text":"agent"}')])
        else:
            yield content_delta_event("已收到 MCP 返回结果。")
        yield done_event()


async def test_agent_discovers_confirms_calls_and_reinjects_result(tmp_path: Path) -> None:
    fixture = Path(__file__).parent / "fixtures" / "mcp_test_server.py"
    raw = {
        "mcp_servers": {
            "live": {
                "transport": "stdio",
                "command": sys.executable,
                "args": [str(fixture)],
            }
        }
    }
    configs, issues = load_mcp_configuration(raw, tmp_path)
    manager = McpManager(configs, tmp_path, issues)
    try:
        await manager.start()
        registry = create_default_tool_registry()
        registry.register_many(manager.adapters)
        echo = next(tool for tool in manager.adapters if tool.remote_name == "echo")
        context = ToolExecutionContext(AllowedPathPolicy((tmp_path,)), default_cwd=tmp_path)
        approver = Approver()
        provider = Provider(echo.name)
        conversation = ConversationContext()
        executor = ToolBatchExecutor(registry, context, approver=approver)
        loop = AgentLoop(provider, conversation, registry, context, tool_executor=executor)

        events = [event async for event in loop.run(AgentRunRequest("调用 echo", NORMAL_AGENT_MODE))]

        assert events
        assert approver.count == 1
        tool_message = next(message for message in provider.messages[1] if message.get("role") == "tool")
        payload = json.loads(tool_message["content"])
        assert payload["ok"] is True
        assert "echo:agent" in payload["content"]
        exposed = provider.messages[0][-1]["content"]
        assert "<system-reminder>" in exposed
    finally:
        await manager.close()


@pytest.mark.ch10_5
@pytest.mark.parametrize(
    "scenario",
    ["normal-approved", "plan-approved", "normal-denied", "plan-denied", "remote-failure"],
)
async def test_mcp_adapter_permission_and_explicit_mode_isolation(
    tmp_path: Path,
    scenario: str,
) -> None:
    class RemoteManager:
        def __init__(self) -> None:
            self.calls = 0

        async def call_tool(self, server_name, tool_name, arguments):
            self.calls += 1
            if scenario == "remote-failure":
                raise RuntimeError("remote unavailable")
            return SimpleNamespace(
                content=(SimpleNamespace(type="text", text="remote-ok"),),
                structuredContent=None,
                isError=False,
            )

    class ExplicitApprover:
        def __init__(self) -> None:
            self.plan_modes: list[bool] = []

        async def request_mcp_approval(self, preview, plan_mode: bool) -> bool:
            self.plan_modes.append(plan_mode)
            return "denied" not in scenario

        async def request_approval(self, request):
            raise AssertionError("MCP must use its dedicated approval path")

    remote = RemoteManager()
    adapter = create_adapter(
        remote,
        "server",
        SimpleNamespace(
            name="echo",
            description="echo",
            inputSchema={"type": "object", "properties": {}},
        ),
    )
    registry = create_default_tool_registry()
    registry.register(adapter)
    context = ToolExecutionContext(
        AllowedPathPolicy((tmp_path,)),
        default_cwd=tmp_path,
        permission_state=PermissionState(),
    )
    approver = ExplicitApprover()
    permissions = PermissionService(PermissionState(), approver=approver)
    service = ToolExecutionService(registry, context, permissions)
    mode = PLAN_MODE if scenario.startswith("plan") else NORMAL_AGENT_MODE

    plan = service.build_plan(
        [ToolCall("mcp", adapter.name, "{}")],
        mode.tool_policy,
    )
    events = [event async for event in service.execute_plan(plan, mode=mode)]
    result = events[-1].payload["result"]

    assert approver.plan_modes == [mode is PLAN_MODE]
    if "denied" in scenario:
        assert not result.ok
        assert result.status == "denied"
        assert remote.calls == 0
    elif scenario == "remote-failure":
        assert not result.ok
        assert result.error_code == "mcp_call_failed"
        (tmp_path / "healthy.txt").write_text("builtin-ok", encoding="utf-8")
        builtin_plan = service.build_plan(
            [ToolCall("read", "read_file", '{"path":"healthy.txt"}')],
            NORMAL_AGENT_MODE.tool_policy,
        )
        builtin_events = [
            event async for event in service.execute_plan(builtin_plan, mode=NORMAL_AGENT_MODE)
        ]
        assert builtin_events[-1].payload["result"].ok
        assert "builtin-ok" in builtin_events[-1].payload["result"].content
    else:
        assert result.ok
        assert "remote-ok" in result.content
