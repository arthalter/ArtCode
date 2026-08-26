from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

import artcode.mcp.session as session_module
import artcode.mcp.transport as transport_module
from artcode.mcp.models import McpServerConfig, ServerSource, ServerState, TransportKind
from artcode.mcp.session import McpSession
from artcode.mcp.stderr import StderrCapture
from artcode.mcp.transport import open_transport


def _stdio(name: str = "server") -> McpServerConfig:
    return McpServerConfig(
        name,
        TransportKind.STDIO,
        ServerSource.USER,
        True,
        command="python",
        args=("server.py",),
        env={"TOKEN": "secret"},
    )


def _http() -> McpServerConfig:
    return McpServerConfig(
        "server",
        TransportKind.STREAMABLE_HTTP,
        ServerSource.USER,
        True,
        url="https://example.invalid/mcp",
        headers={"Authorization": "secret"},
    )


def test_stderr_capture_bounds_lines_bytes_and_redacts() -> None:
    capture = StderrCapture(("secret",))
    capture.stream.write("old\nsecret " + "x" * 30 + "\nlast\n")
    assert "old" not in capture.recent(max_lines=2, max_bytes=20, line_limit=12)
    assert "secret" not in capture.recent()
    capture.close()


async def test_stdio_transport_closes_capture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    observed = {}

    @asynccontextmanager
    async def fake_stdio(params, errlog):
        observed["params"] = params
        observed["capture"] = errlog
        yield ("read", "write")

    monkeypatch.setattr(transport_module, "stdio_client", fake_stdio)
    async with open_transport(_stdio(), tmp_path) as (streams, capture):
        assert streams == ("read", "write")
        assert capture is not None
        assert observed["params"].cwd == tmp_path
    assert capture.stream.closed


async def test_http_transport_restores_headers_and_closes_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class Client:
        def __init__(self, **kwargs):
            self.hook = kwargs["event_hooks"]["request"][0]
            self.closed = False

        async def aclose(self):
            self.closed = True

    client_holder = {}

    def make_client(**kwargs):
        client_holder["client"] = Client(**kwargs)
        return client_holder["client"]

    @asynccontextmanager
    async def fake_http(url, http_client):
        request = SimpleNamespace(headers={})
        await http_client.hook(request)
        assert request.headers["Authorization"] == "secret"
        yield ("read", "write", "session-id")

    monkeypatch.setattr(transport_module.httpx, "AsyncClient", make_client)
    monkeypatch.setattr(transport_module, "streamable_http_client", fake_http)
    async with open_transport(_http(), tmp_path) as (streams, capture):
        assert streams == ("read", "write")
        assert capture is None
    assert client_holder["client"].closed


async def test_closed_session_cannot_connect(tmp_path: Path) -> None:
    session = McpSession(_stdio(), tmp_path)
    await session.close()
    with pytest.raises(RuntimeError, match="不能重新连接"):
        await session.connect()


async def test_connect_failure_marks_unavailable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    @asynccontextmanager
    async def fail_transport(config, workspace):
        raise ConnectionError("offline")
        yield

    monkeypatch.setattr(session_module, "open_transport", fail_transport)
    session = McpSession(_stdio(), tmp_path)
    with pytest.raises(ConnectionError):
        await session.connect()
    assert session.state is ServerState.UNAVAILABLE
    assert session._closed


@pytest.mark.parametrize("scenario", ["limit", "repeat", "hundred-pages"])
async def test_tool_discovery_guards_unbounded_pagination(tmp_path: Path, scenario: str) -> None:
    calls = 0

    class Client:
        async def list_tools(self, cursor=None):
            nonlocal calls
            calls += 1
            if scenario == "limit":
                return SimpleNamespace(tools=list(range(101)), nextCursor="more")
            if scenario == "repeat":
                return SimpleNamespace(tools=[calls], nextCursor="same")
            return SimpleNamespace(tools=[], nextCursor=str(calls))

    session = McpSession(_stdio(), tmp_path)
    session._client = Client()
    tools = await session._discover_tools()
    assert session.truncated
    if scenario == "limit":
        # The discovery loop caps at MCP_MAX_DISCOVERED_TOOLS (500) but the
        # repeating cursor protection stops after two pages, leaving the
        # partial 202 tools marked truncated.
        assert len(tools) == 202
    elif scenario == "repeat":
        assert len(tools) == 2
    else:
        assert calls == 100


async def test_unavailable_call_and_timeout_are_observable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    session = McpSession(_stdio("slow"), tmp_path)
    with pytest.raises(RuntimeError, match="不可用"):
        await session.call_tool("x", {})

    class Client:
        async def call_tool(self, *args, **kwargs):
            raise TimeoutError

    session._client = Client()
    session.state = ServerState.READY
    with pytest.raises(RuntimeError, match="调用超时"):
        await session.call_tool("x", {})
    assert session.state is ServerState.UNAVAILABLE


async def test_call_cancellation_is_preserved(tmp_path: Path) -> None:
    class Client:
        async def call_tool(self, *args, **kwargs):
            raise asyncio.CancelledError

    session = McpSession(_stdio(), tmp_path)
    session._client = Client()
    session.state = ServerState.READY
    with pytest.raises(asyncio.CancelledError):
        await session.call_tool("x", {})
    await session.close()


async def test_close_is_idempotent_and_tolerates_stack_failure(tmp_path: Path) -> None:
    class Stack:
        async def aclose(self):
            raise RuntimeError("cleanup")

    session = McpSession(_stdio(), tmp_path)
    session._stack = Stack()
    await session.close()
    await session.close()
    assert session.state is ServerState.CLOSED
