from __future__ import annotations

from contextlib import asynccontextmanager
import tempfile

import httpx
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client

from .mcp_config import ServerConfig, safe_environment


@asynccontextmanager
async def open_transport(config: ServerConfig, workspace: str):
    if config.transport == "stdio":
        parameters = StdioServerParameters(
            command=config.command or "",
            args=list(config.args),
            env=safe_environment(config),
            cwd=workspace,
        )
        with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as stderr:
            async with stdio_client(parameters, errlog=stderr) as streams:
                yield streams
        return

    headers = dict(config.headers)

    async def restore_configured_headers(request: httpx.Request) -> None:
        for name, value in headers.items():
            request.headers[name] = value

    client = httpx.AsyncClient(
        headers=headers,
        follow_redirects=True,
        max_redirects=10,
        timeout=httpx.Timeout(10.0),
        event_hooks={"request": [restore_configured_headers]},
    )
    try:
        async with streamable_http_client(config.url or "", http_client=client) as streams:
            yield streams[:2]
    finally:
        await client.aclose()
