from __future__ import annotations

from contextlib import asynccontextmanager

import httpx
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client

from .config import safe_stdio_environment
from .models import McpServerConfig, TransportKind
from .stderr import StderrCapture


@asynccontextmanager
async def open_transport(config: McpServerConfig, workspace):
    if config.transport is TransportKind.STDIO:
        capture = StderrCapture(tuple(config.env.values()))
        params = StdioServerParameters(
            command=config.command or "",
            args=list(config.args),
            env=safe_stdio_environment(config.env),
            cwd=workspace,
        )
        try:
            async with stdio_client(params, errlog=capture.stream) as streams:
                yield streams, capture
        finally:
            capture.close()
        return
    configured_headers = dict(config.headers)

    async def restore_configured_headers(request: httpx.Request) -> None:
        # HTTPX intentionally strips Authorization on cross-origin redirects.
        # ch07 explicitly chooses compatibility over that default protection.
        for name, value in configured_headers.items():
            request.headers[name] = value

    client = httpx.AsyncClient(
        headers=configured_headers, follow_redirects=True, max_redirects=10,
        timeout=httpx.Timeout(10.0),
        event_hooks={"request": [restore_configured_headers]},
    )
    try:
        async with streamable_http_client(config.url or "", http_client=client) as streams:
            yield streams[:2], None
    finally:
        await client.aclose()
