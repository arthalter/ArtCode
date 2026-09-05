from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from dataclasses import dataclass
from datetime import timedelta
import json
from typing import Any, Mapping

from mcp import ClientSession

from artcode.core.tool import (
    McpLoading,
    McpReport,
    McpServerApprover,
    McpServerReport,
    McpServerSource,
    McpServerState,
    McpToolHit,
    ToolCall,
    ToolDescriptor,
    ToolEffect,
    ToolOrigin,
    ToolResult,
    ToolRun,
)

from .builtin import Prepared
from .mcp_config import ServerConfig, load_configs, registered_name
from .mcp_results import convert_result, sanitize
from .mcp_transport import open_transport
from .results import failure


CONNECT_TIMEOUT = 10.0
READ_TIMEOUT = 60.0
MAX_TOOLS = 500
MAX_PAGES = 100


@dataclass
class _Session:
    config: ServerConfig
    workspace: str
    tool_timeout: float

    def __post_init__(self) -> None:
        self.stack = AsyncExitStack()
        self.client: ClientSession | None = None
        self.state = McpServerState.UNAVAILABLE
        self.tools: tuple[Any, ...] = ()
        self.truncated = False
        self.closed = False

    async def connect(self) -> tuple[Any, ...]:
        streams = await self.stack.enter_async_context(
            open_transport(self.config, self.workspace)
        )
        self.client = await self.stack.enter_async_context(
            ClientSession(
                *streams,
                read_timeout_seconds=timedelta(seconds=READ_TIMEOUT),
            )
        )
        await asyncio.wait_for(self.client.initialize(), CONNECT_TIMEOUT)
        found: list[Any] = []
        cursor: str | None = None
        seen: set[str] = set()
        for _ in range(MAX_PAGES):
            page = await asyncio.wait_for(self.client.list_tools(cursor=cursor), CONNECT_TIMEOUT)
            remaining = MAX_TOOLS - len(found)
            found.extend(list(page.tools)[:remaining])
            if len(found) >= MAX_TOOLS:
                self.truncated = bool(page.nextCursor) or len(page.tools) > remaining
                break
            cursor = page.nextCursor
            if not cursor:
                break
            if cursor in seen:
                self.truncated = True
                break
            seen.add(cursor)
        else:
            self.truncated = True
        self.tools = tuple(found)
        self.state = McpServerState.READY
        return self.tools

    async def call(self, name: str, arguments: dict[str, Any]) -> Any:
        if self.state is not McpServerState.READY or self.client is None:
            raise RuntimeError(f"MCP Server {self.config.name} 不可用。")
        return await asyncio.wait_for(
            self.client.call_tool(
                name,
                arguments,
                read_timeout_seconds=timedelta(seconds=self.tool_timeout),
            ),
            self.tool_timeout,
        )

    async def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            await self.stack.aclose()
        except BaseException:
            pass
        if self.state is not McpServerState.UNAVAILABLE:
            self.state = McpServerState.CLOSED


@dataclass(frozen=True, slots=True)
class _McpTool:
    descriptor: ToolDescriptor
    remote_name: str
    server_name: str
    session: _Session


class McpAdapter:
    def __init__(self, workspace: str, *, tool_timeout: float = 60.0) -> None:
        self.workspace = workspace
        self.tool_timeout = tool_timeout
        self.sessions: dict[str, _Session] = {}
        self.tools: dict[str, _McpTool] = {}
        self.active_names: set[str] = set()
        self.loading = McpLoading.EAGER
        self.report = McpReport(0, (), 0, 0, self.loading)
        self._calls: set[asyncio.Task[Any]] = set()
        self._closed = False

    @property
    def active_descriptors(self) -> tuple[ToolDescriptor, ...]:
        return tuple(
            self.tools[name].descriptor for name in sorted(self.active_names) if name in self.tools
        )

    @property
    def all_descriptors(self) -> tuple[ToolDescriptor, ...]:
        return tuple(tool.descriptor for _, tool in sorted(self.tools.items()))

    async def start(
        self,
        user: Mapping[str, Any],
        project: Mapping[str, Any],
        *,
        loading: McpLoading,
        approver: McpServerApprover | None,
    ) -> McpReport:
        configs, issue_reports = load_configs(user, project)
        reports: list[McpServerReport] = list(issue_reports)
        for config in configs:
            if not config.enabled:
                reports.append(McpServerReport(config.name, config.source, McpServerState.DISABLED))
                continue
            if config.source is McpServerSource.PROJECT:
                if approver is None:
                    reports.append(McpServerReport(config.name, config.source, McpServerState.REJECTED))
                    continue
                try:
                    allowed = await approver.approve_mcp_server(config.name, config.summary)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    reports.append(
                        McpServerReport(
                            config.name,
                            config.source,
                            McpServerState.UNAVAILABLE,
                            detail=sanitize(exc, config.secrets),
                        )
                    )
                    continue
                if not allowed:
                    reports.append(McpServerReport(config.name, config.source, McpServerState.REJECTED))
                    continue
            session = _Session(config, self.workspace, self.tool_timeout)
            try:
                remote_tools = await session.connect()
            except asyncio.CancelledError:
                await session.close()
                raise
            except BaseException as exc:
                session.state = McpServerState.UNAVAILABLE
                await session.close()
                reports.append(
                    McpServerReport(
                        config.name,
                        config.source,
                        McpServerState.UNAVAILABLE,
                        detail=sanitize(exc, config.secrets),
                    )
                )
                continue
            self.sessions[config.name] = session
            accepted = 0
            for remote in remote_tools:
                try:
                    tool = self._make_tool(config.name, session, remote)
                except ValueError:
                    continue
                if tool.descriptor.name in self.tools:
                    continue
                self.tools[tool.descriptor.name] = tool
                accepted += 1
            reports.append(
                McpServerReport(
                    config.name,
                    config.source,
                    McpServerState.READY,
                    tool_count=accepted,
                    truncated=session.truncated,
                )
            )
        self.loading = loading
        self.active_names = set(self.tools) if loading is McpLoading.EAGER else set()
        self.report = McpReport(
            configured_count=len(configs) + len(issue_reports),
            servers=tuple(reports),
            discovered_tool_count=len(self.tools),
            active_tool_count=len(self.active_names),
            loading=loading,
        )
        return self.report

    def search(self, query: str, *, limit: int) -> tuple[McpToolHit, ...]:
        if not isinstance(query, str) or not query.strip() or limit < 1:
            raise ValueError("MCP 搜索词和 limit 必须有效。")
        words = query.casefold().split()
        hits: list[McpToolHit] = []
        for name, tool in sorted(self.tools.items()):
            haystack = f"{name} {tool.descriptor.description} {tool.server_name}".casefold()
            if all(word in haystack for word in words):
                hits.append(McpToolHit(name, tool.descriptor.description, tool.server_name, name in self.active_names))
        return tuple(hits[:limit])

    def activate(self, name: str) -> bool:
        if name not in self.tools:
            return False
        self.active_names.add(name)
        self.report = McpReport(
            self.report.configured_count,
            self.report.servers,
            self.report.discovered_tool_count,
            len(self.active_names),
            self.report.loading,
        )
        return True

    def descriptor(self, name: str) -> ToolDescriptor | None:
        tool = self.tools.get(name)
        return tool.descriptor if tool else None

    def prepare(self, call: ToolCall, arguments: dict[str, Any], run: ToolRun) -> Prepared | ToolResult:
        tool = self.tools.get(call.name)
        if tool is None:
            return failure(call, "tool_not_found", f"未知 MCP 工具：{call.name}")

        async def execute() -> ToolResult:
            if self._closed:
                return failure(call, "mcp_call_failed", "MCP Adapter 已关闭。")
            task = asyncio.create_task(tool.session.call(tool.remote_name, arguments))
            self._calls.add(task)
            try:
                result = await task
                return convert_result(call, result)
            except asyncio.CancelledError:
                raise
            except BaseException as exc:
                tool.session.state = McpServerState.UNAVAILABLE
                return failure(call, "mcp_call_failed", sanitize(exc, tool.session.config.secrets))
            finally:
                self._calls.discard(task)

        target = f"{tool.server_name}/{tool.remote_name}"
        return Prepared(call, tool.descriptor, target, execute)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        active = tuple(self._calls)
        for task in active:
            task.cancel()
        if active:
            await asyncio.gather(*active, return_exceptions=True)
        for session in self.sessions.values():
            await session.close()

    @staticmethod
    def _make_tool(server: str, session: _Session, remote: Any) -> _McpTool:
        name = getattr(remote, "name", None)
        schema = getattr(remote, "inputSchema", None)
        if not isinstance(name, str) or not name.strip():
            raise ValueError("MCP Tool 缺少名称。")
        if not isinstance(schema, dict) or schema.get("type") != "object":
            raise ValueError("MCP Tool inputSchema 必须是 object。")
        description = getattr(remote, "description", None)
        if not isinstance(description, str) or not description.strip():
            description = f"来自 MCP Server {server} 的工具 {name}。"
        descriptor = ToolDescriptor(
            registered_name(server, name),
            description,
            json.dumps(schema, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
            ToolEffect.EXTERNAL,
            origin=ToolOrigin.MCP,
            subagent_allowed=False,
            rule_configurable=False,
        )
        return _McpTool(descriptor, name, server, session)
