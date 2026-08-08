from __future__ import annotations

import json
import sys
from pathlib import Path

from artcode.agent import AgentLoop, AgentRunRequest, NORMAL_AGENT_MODE
from artcode.agent.tools import ToolBatchExecutor
from artcode.conversation import ConversationContext
from artcode.mcp.config import load_mcp_configuration
from artcode.mcp.manager import McpManager
from artcode.providers.events import content_delta_event, done_event, tool_calls_event
from artcode.providers.tool_calls import ToolCall
from artcode.tools import AllowedPathPolicy, ToolExecutionContext, create_default_tool_registry


class Approver:
    def __init__(self) -> None:
        self.count = 0

    async def request_mcp_approval(self, preview) -> bool:
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
