from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from datetime import timedelta
from typing import Any

from mcp import ClientSession

from .models import McpServerConfig, ServerState
from .redaction import sanitize_external_text
from .transport import open_transport


class McpSession:
    def __init__(self, config: McpServerConfig, workspace) -> None:
        self.config = config
        self.workspace = workspace
        self.state = ServerState.CONNECTING
        self.tools: tuple[Any, ...] = ()
        self.truncated = False
        self._stack = AsyncExitStack()
        self._client: ClientSession | None = None
        self._closing = False

    async def connect(self) -> tuple[Any, ...]:
        try:
            streams, _capture = await asyncio.wait_for(
                self._stack.enter_async_context(open_transport(self.config, self.workspace)), 10
            )
            self._client = await self._stack.enter_async_context(
                ClientSession(*streams, read_timeout_seconds=timedelta(seconds=60))
            )
            await asyncio.wait_for(self._client.initialize(), 10)
            self.tools = await self._discover_tools()
            self.state = ServerState.READY
            return self.tools
        except BaseException:
            self.state = ServerState.UNAVAILABLE
            await self.close()
            raise

    async def _discover_tools(self) -> tuple[Any, ...]:
        assert self._client is not None
        found: list[Any] = []
        cursor: str | None = None
        seen: set[str] = set()
        for _ in range(100):
            result = await asyncio.wait_for(self._client.list_tools(cursor=cursor), 10)
            remaining = 100 - len(found)
            found.extend(list(result.tools)[:remaining])
            if len(found) >= 100:
                self.truncated = bool(result.nextCursor) or len(result.tools) > remaining
                break
            cursor = result.nextCursor
            if not cursor:
                break
            if cursor in seen:
                self.truncated = True
                break
            seen.add(cursor)
        else:
            self.truncated = True
        return tuple(found)

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        if self.state is not ServerState.READY or self._client is None:
            raise RuntimeError(f"MCP Server {self.config.name} 当前不可用。")
        try:
            return await asyncio.wait_for(
                self._client.call_tool(name, arguments, read_timeout_seconds=timedelta(seconds=60)), 60
            )
        except TimeoutError:
            self.state = ServerState.UNAVAILABLE
            await self.close()
            raise RuntimeError(f"MCP Server {self.config.name} 调用超时，已标记不可用。") from None
        except (ConnectionError, EOFError, BrokenPipeError) as exc:
            self.state = ServerState.UNAVAILABLE
            await self.close()
            raise RuntimeError(sanitize_external_text(f"MCP Server {self.config.name} 连接已断开：{exc}")) from None
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.state = ServerState.UNAVAILABLE
            await self.close()
            raise RuntimeError(
                sanitize_external_text(f"MCP Server {self.config.name} 协议调用失败：{exc}")
            ) from None

    async def close(self) -> None:
        if self._closing or self.state is ServerState.CLOSED:
            return
        self._closing = True
        try:
            await asyncio.wait_for(self._stack.aclose(), 5)
        except Exception:
            pass
        finally:
            if self.state is not ServerState.UNAVAILABLE:
                self.state = ServerState.CLOSED
            self._closing = False
