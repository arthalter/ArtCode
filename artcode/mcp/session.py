from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from datetime import timedelta
from typing import Any

from mcp import ClientSession

from .models import McpServerConfig, ServerState
from .redaction import sanitize_external_text
from .transport import open_transport


MCP_CONNECT_TIMEOUT_SECONDS = 10.0
MCP_SESSION_READ_TIMEOUT_SECONDS = 60.0
MCP_TOOL_TIMEOUT_SECONDS = 60.0
MCP_CLOSE_TIMEOUT_SECONDS = 5.0
MCP_MAX_DISCOVERED_TOOLS = 500
MCP_MAX_DISCOVERY_PAGES = 100


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
        self._closed = False
        self._close_lock = asyncio.Lock()

    async def connect(self) -> tuple[Any, ...]:
        if self._closed:
            raise RuntimeError("已经关闭的 MCP Session 不能重新连接。")
        try:
            streams, _capture = await asyncio.wait_for(
                self._stack.enter_async_context(open_transport(self.config, self.workspace)),
                MCP_CONNECT_TIMEOUT_SECONDS,
            )
            self._client = await self._stack.enter_async_context(
                ClientSession(
                    *streams,
                    read_timeout_seconds=timedelta(
                        seconds=MCP_SESSION_READ_TIMEOUT_SECONDS
                    ),
                )
            )
            await asyncio.wait_for(
                self._client.initialize(), MCP_CONNECT_TIMEOUT_SECONDS
            )
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
        for _ in range(MCP_MAX_DISCOVERY_PAGES):
            result = await asyncio.wait_for(
                self._client.list_tools(cursor=cursor), MCP_CONNECT_TIMEOUT_SECONDS
            )
            remaining = MCP_MAX_DISCOVERED_TOOLS - len(found)
            found.extend(list(result.tools)[:remaining])
            if len(found) >= MCP_MAX_DISCOVERED_TOOLS:
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
                self._client.call_tool(
                    name,
                    arguments,
                    read_timeout_seconds=timedelta(seconds=MCP_TOOL_TIMEOUT_SECONDS),
                ),
                MCP_TOOL_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            self.state = ServerState.UNAVAILABLE
            await self.close()
            raise RuntimeError(f"MCP Server {self.config.name} 调用超时，已标记不可用。") from None
        except (ConnectionError, EOFError, BrokenPipeError) as exc:
            self.state = ServerState.UNAVAILABLE
            await self.close()
            raise RuntimeError(
                sanitize_external_text(
                    f"MCP Server {self.config.name} 连接已断开：{exc}",
                    self._secrets,
                )
            ) from None
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.state = ServerState.UNAVAILABLE
            await self.close()
            raise RuntimeError(
                sanitize_external_text(
                    f"MCP Server {self.config.name} 协议调用失败：{exc}",
                    self._secrets,
                )
            ) from None

    async def close(self) -> None:
        async with self._close_lock:
            if self._closed:
                return
            self._closing = True
            try:
                await asyncio.wait_for(
                    self._stack.aclose(), MCP_CLOSE_TIMEOUT_SECONDS
                )
            except Exception:
                pass
            finally:
                self._closed = True
                if self.state is not ServerState.UNAVAILABLE:
                    self.state = ServerState.CLOSED
                self._closing = False

    @property
    def _secrets(self) -> tuple[str, ...]:
        return tuple(self.config.env.values()) + tuple(self.config.headers.values())
