from __future__ import annotations

import asyncio
import json
from pathlib import Path
import socket
import sys

import httpx

from artcode._tool import LocalTools
from artcode._workspace import LocalWorkspace
from artcode.core.tool import ApprovalChoice, PermissionMode, RunMode, ToolCall


class Allow:
    async def approve(self, request):
        return ApprovalChoice.ALLOW_ONCE


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


async def test_real_streamable_http_initializes_discovers_calls_and_closes(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    workspace = LocalWorkspace(root)
    port = free_port()
    fixture = Path(__file__).parent / "fixtures" / "mcp_test_server.py"
    process = await asyncio.create_subprocess_exec(
        sys.executable, str(fixture), "--transport", "streamable-http", "--port", str(port),
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    tools = LocalTools(permission_mode=PermissionMode.FULL)
    try:
        async with httpx.AsyncClient() as client:
            for _ in range(100):
                try:
                    if (await client.get(f"http://127.0.0.1:{port}/mcp")).status_code < 500:
                        break
                except httpx.TransportError:
                    pass
                await asyncio.sleep(0.05)
            else:
                raise AssertionError("HTTP MCP fixture did not start")
        report = await tools.start_mcp(
            workspace,
            {"http": {"transport": "streamable_http", "url": f"http://127.0.0.1:{port}/mcp"}},
            {},
        )
        run = tools.open_run(workspace, RunMode.CHAT)
        echo = next(item.name for item in run.descriptors if item.name.endswith("__echo"))
        result = await tools.execute_batch(
            run,
            (ToolCall("1", echo, json.dumps({"text": "http"})),),
            approver=Allow(),
        )
        assert report.connected_count == 1
        assert result[0].ok is True and "echo:http" in result[0].content
    finally:
        await tools.close()
        process.terminate()
        await process.wait()
