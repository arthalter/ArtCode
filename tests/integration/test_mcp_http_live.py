import asyncio
import socket
import sys
from pathlib import Path

import httpx

from artcode.mcp.config import load_mcp_configuration
from artcode.mcp.manager import McpManager


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


async def test_real_streamable_http_discovers_and_calls(tmp_path: Path) -> None:
    port = free_port()
    fixture = Path(__file__).parent / "fixtures" / "mcp_test_server.py"
    process = await asyncio.create_subprocess_exec(
        sys.executable, str(fixture), "--transport", "streamable-http", "--port", str(port),
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    manager = None
    try:
        async with httpx.AsyncClient() as client:
            for _ in range(100):
                try:
                    response = await client.get(f"http://127.0.0.1:{port}/mcp")
                    if response.status_code < 500:
                        break
                except httpx.TransportError:
                    pass
                await asyncio.sleep(0.05)
            else:
                raise AssertionError("HTTP MCP test server did not start")
        raw = {"mcp_servers": {"http": {"transport": "streamable_http", "url": f"http://127.0.0.1:{port}/mcp"}}}
        configs, issues = load_mcp_configuration(raw, tmp_path)
        manager = McpManager(configs, tmp_path, issues)
        report = await manager.start()
        assert report.connected_count == 1
        result = await manager.call_tool("http", "echo", {"text": "world"})
        assert "echo:world" in result.content[0].text
    finally:
        if manager is not None:
            await manager.close()
        process.terminate()
        await process.wait()
