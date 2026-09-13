from __future__ import annotations

import argparse
import asyncio
import os
import sys

from mcp.server.fastmcp import FastMCP


def build_server(host: str, port: int) -> FastMCP:
    server = FastMCP("ArtCode ch07 test", host=host, port=port, log_level="ERROR")

    @server.tool()
    def echo(text: str) -> str:
        """Return the provided text."""
        return f"echo:{text}"

    @server.tool()
    async def delayed(text: str, milliseconds: int = 10) -> str:
        """Return text after a controlled delay."""
        await asyncio.sleep(milliseconds / 1000)
        return text

    @server.tool()
    def fail(message: str) -> str:
        """Raise a controlled tool business error."""
        raise ValueError(message)

    @server.tool()
    def disconnect() -> str:
        """Terminate this test Server immediately."""
        os._exit(23)

    return server


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--transport", choices=("stdio", "streamable-http"), default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--stderr-lines", type=int, default=0)
    args = parser.parse_args()
    for index in range(args.stderr_lines):
        print(f"diagnostic-{index}", file=sys.stderr)
    server = build_server(args.host, args.port)
    server.run(transport=args.transport)


if __name__ == "__main__":
    main()
