import asyncio
from pathlib import Path

import pytest

pytestmark = pytest.mark.live

from artcode.mcp.config import load_mcp_configuration
from artcode.mcp.manager import McpManager
from artcode.mcp.models import ServerState


async def test_real_stdio_server_discovers_and_calls(tmp_path: Path) -> None:
    fixture = Path(__file__).parent / "fixtures" / "mcp_test_server.py"
    raw = {
        "mcp_servers": {
            "live": {
                "transport": "stdio",
                "command": str(Path(__import__("sys").executable)),
                "args": [str(fixture), "--stderr-lines", "5000"],
            }
        }
    }
    configs, issues = load_mcp_configuration(raw, tmp_path)
    manager = McpManager(configs, tmp_path, issues)
    try:
        report = await manager.start()
        assert report.connected_count == 1
        assert {tool.remote_name for tool in manager.adapters} >= {"echo", "delayed", "fail"}
        result = await manager.call_tool("live", "echo", {"text": "hello"})
        assert "echo:hello" in result.content[0].text
    finally:
        await manager.close()


async def test_disconnected_server_does_not_break_another_server(tmp_path: Path) -> None:
    fixture = Path(__file__).parent / "fixtures" / "mcp_test_server.py"
    server = {
        "transport": "stdio",
        "command": str(Path(__import__("sys").executable)),
        "args": [str(fixture)],
    }
    configs, issues = load_mcp_configuration({"mcp_servers": {"broken": server, "healthy": server}}, tmp_path)
    manager = McpManager(configs, tmp_path, issues)
    try:
        report = await manager.start()
        assert report.connected_count == 2
        try:
            await manager.call_tool("broken", "disconnect", {})
        except RuntimeError:
            pass
        assert manager.sessions["broken"].state is ServerState.UNAVAILABLE
        result = await manager.call_tool("healthy", "echo", {"text": "still-ok"})
        assert "echo:still-ok" in result.content[0].text
    finally:
        await manager.close()


async def test_cancelled_real_stdio_call_keeps_healthy_session_reusable(tmp_path: Path) -> None:
    fixture = Path(__file__).parent / "fixtures" / "mcp_test_server.py"
    raw = {
        "mcp_servers": {
            "live": {
                "transport": "stdio",
                "command": str(Path(__import__("sys").executable)),
                "args": [str(fixture)],
            }
        }
    }
    configs, issues = load_mcp_configuration(raw, tmp_path)
    manager = McpManager(configs, tmp_path, issues)
    try:
        await manager.start()
        slow = asyncio.create_task(
            manager.call_tool("live", "delayed", {"text": "late", "milliseconds": 5_000})
        )
        await asyncio.sleep(0.05)
        slow.cancel()
        result = await asyncio.gather(slow, return_exceptions=True)
        assert isinstance(result[0], asyncio.CancelledError)
        assert not manager._active_calls

        follow_up = await manager.call_tool("live", "echo", {"text": "reused"})
        assert "echo:reused" in follow_up.content[0].text
    finally:
        await manager.close()
