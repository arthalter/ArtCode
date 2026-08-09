from __future__ import annotations

import asyncio
import socket
import sys
from pathlib import Path

import httpx
import pytest

import artcode.mcp.session as session_module
from artcode.mcp.config import load_mcp_configuration
from artcode.mcp.manager import McpManager
from artcode.mcp.models import ServerState


pytestmark = [pytest.mark.ch10_5, pytest.mark.live]
FIXTURE = Path(__file__).resolve().parents[1] / "integration" / "fixtures" / "mcp_test_server.py"


def _stdio(name: str = "live", *extra_args: str):
    return {
        "mcp_servers": {
            name: {
                "transport": "stdio",
                "command": sys.executable,
                "args": [str(FIXTURE), *extra_args],
            }
        }
    }


def _manager(raw: dict, workspace: Path) -> McpManager:
    configs, issues = load_mcp_configuration(raw, workspace)
    return McpManager(configs, workspace, issues)


async def test_real_stdio_discovery_call_and_deterministic_close(tmp_path: Path) -> None:
    manager = _manager(_stdio("stdio", "--stderr-lines", "1000"), tmp_path)
    report = await manager.start()
    session = manager.sessions["stdio"]

    result = await manager.call_tool("stdio", "echo", {"text": "live-stdio"})
    await manager.close()

    assert report.connected_count == 1
    assert {adapter.remote_name for adapter in manager.adapters} >= {"echo", "delayed", "fail"}
    assert "echo:live-stdio" in result.content[0].text
    assert session.state is ServerState.CLOSED
    assert not manager._active_calls


async def test_real_stdio_cancelled_call_keeps_session_reusable(tmp_path: Path) -> None:
    manager = _manager(_stdio(), tmp_path)
    try:
        await manager.start()
        slow = asyncio.create_task(
            manager.call_tool("live", "delayed", {"text": "late", "milliseconds": 5_000})
        )
        await asyncio.sleep(0.05)
        slow.cancel()
        outcome = await asyncio.gather(slow, return_exceptions=True)
        assert isinstance(outcome[0], asyncio.CancelledError)
        assert not manager._active_calls

        follow_up = await manager.call_tool("live", "echo", {"text": "after-cancel"})
        assert "echo:after-cancel" in follow_up.content[0].text
        assert manager.sessions["live"].state is ServerState.READY
    finally:
        await manager.close()


async def test_real_disconnected_stdio_server_isolated_from_healthy_peer(tmp_path: Path) -> None:
    server = _stdio("broken")["mcp_servers"]["broken"]
    manager = _manager({"mcp_servers": {"broken": server, "healthy": server}}, tmp_path)
    try:
        report = await manager.start()
        assert report.connected_count == 2
        with pytest.raises(RuntimeError):
            await manager.call_tool("broken", "disconnect", {})
        assert manager.sessions["broken"].state is ServerState.UNAVAILABLE

        result = await manager.call_tool("healthy", "echo", {"text": "peer-ok"})
        assert "echo:peer-ok" in result.content[0].text
        assert manager.sessions["healthy"].state is ServerState.READY
    finally:
        await manager.close()


async def test_real_stdio_timeout_marks_only_that_session_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(session_module, "MCP_TOOL_TIMEOUT_SECONDS", 0.05)
    manager = _manager(_stdio(), tmp_path)
    try:
        await manager.start()
        with pytest.raises(RuntimeError, match="超时"):
            await manager.call_tool(
                "live",
                "delayed",
                {"text": "late", "milliseconds": 5_000},
            )
        assert manager.sessions["live"].state is ServerState.UNAVAILABLE
        assert not manager._active_calls
    finally:
        await manager.close()


async def test_real_streamable_http_headers_discovery_call_and_close(tmp_path: Path) -> None:
    port = _free_port()
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        str(FIXTURE),
        "--transport",
        "streamable-http",
        "--port",
        str(port),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    manager: McpManager | None = None
    try:
        await _wait_http(port)
        raw = {
            "mcp_servers": {
                "http": {
                    "transport": "streamable_http",
                    "url": f"http://127.0.0.1:{port}/mcp",
                    "headers": {"Authorization": "Bearer live-secret"},
                }
            }
        }
        manager = _manager(raw, tmp_path)
        report = await manager.start()
        session = manager.sessions["http"]
        result = await manager.call_tool("http", "echo", {"text": "live-http"})
        await manager.close()

        assert report.connected_count == 1
        assert "echo:live-http" in result.content[0].text
        assert session.state is ServerState.CLOSED
        assert "live-secret" not in str(report)
    finally:
        if manager is not None:
            await manager.close()
        if process.returncode is None:
            process.terminate()
        await process.wait()


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


async def _wait_http(port: int) -> None:
    async with httpx.AsyncClient() as client:
        for _ in range(100):
            try:
                response = await client.get(f"http://127.0.0.1:{port}/mcp")
                if response.status_code < 500:
                    return
            except httpx.TransportError:
                pass
            await asyncio.sleep(0.05)
    raise AssertionError("HTTP MCP test server did not start")
