from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

from .adapter import create_adapter
from .config import expand_config
from .models import (
    FailureStage,
    McpConfigIssue,
    McpServerConfig,
    McpServerReport,
    McpStartupReport,
    ServerSource,
    ServerState,
)
from .redaction import sanitize_external_text
from .session import McpSession


StartupApprover = Callable[[McpServerConfig], Awaitable[bool]]


class McpManager:
    def __init__(
        self,
        configs: tuple[McpServerConfig, ...],
        workspace,
        issues: tuple[McpConfigIssue, ...] = (),
        approver: StartupApprover | None = None,
    ) -> None:
        self.configs = configs
        self.workspace = workspace
        self.issues = issues
        self.approver = approver
        self.sessions: dict[str, McpSession] = {}
        self.adapters: tuple[Any, ...] = ()
        self.report = McpStartupReport(configured_count=len(configs) + len(issues))
        self._accepting = True
        self._active_calls: set[asyncio.Task[Any]] = set()

    async def start(self) -> McpStartupReport:
        semaphore = asyncio.Semaphore(5)

        async def start_one(config: McpServerConfig):
            async with semaphore:
                return await self._start_one(config)

        outcomes = await asyncio.gather(*(start_one(config) for config in self.configs))
        reports = [
            McpServerReport(
                issue.server_name, issue.source, ServerState.INVALID,
                failure_stage=FailureStage.CONFIG, detail=issue.message,
            )
            for issue in self.issues
        ]
        adapter_items: list[Any] = []
        registered_names: set[str] = set()
        for report, adapters in outcomes:
            reports.append(report)
            for adapter in adapters:
                if adapter.name in registered_names:
                    continue
                registered_names.add(adapter.name)
                adapter_items.append(adapter)
        self.adapters = tuple(adapter_items)
        self.report = McpStartupReport(
            configured_count=len(self.configs) + len(self.issues),
            server_reports=tuple(reports),
            registered_tool_count=len(self.adapters),
        )
        return self.report

    async def _start_one(self, config: McpServerConfig):
        if not config.enabled:
            return McpServerReport(config.name, config.source, ServerState.DISABLED), ()
        if config.source is ServerSource.PROJECT:
            if self.approver is None or not await self.approver(config):
                return McpServerReport(config.name, config.source, ServerState.REJECTED), ()
        try:
            expanded = expand_config(config)
        except ValueError as exc:
            return McpServerReport(
                config.name, config.source, ServerState.INVALID,
                failure_stage=FailureStage.CONFIG, detail=str(exc),
            ), ()
        session = McpSession(expanded, self.workspace)
        try:
            tools = await session.connect()
        except Exception as exc:
            secrets = tuple(expanded.env.values()) + tuple(expanded.headers.values())
            return McpServerReport(
                config.name, config.source, ServerState.UNAVAILABLE,
                failure_stage=FailureStage.INITIALIZE,
                detail=sanitize_external_text(str(exc), secrets),
            ), ()
        self.sessions[config.name] = session
        adapters: list[Any] = []
        used: set[str] = set()
        for tool in tools:
            try:
                adapter = create_adapter(self, config.name, tool)
                if adapter.name in used:
                    continue
                used.add(adapter.name)
                adapters.append(adapter)
            except ValueError:
                continue
        return McpServerReport(
            config.name, config.source, ServerState.READY,
            tool_count=len(adapters), truncated=session.truncated,
        ), tuple(adapters)

    async def call_tool(self, server_name: str, tool_name: str, arguments: dict[str, Any]):
        if not self._accepting:
            raise RuntimeError("MCP Manager 正在关闭，不再接受新调用。")
        session = self.sessions.get(server_name)
        if session is None:
            raise RuntimeError(f"MCP Server {server_name} 当前不可用。")
        task = asyncio.create_task(
            session.call_tool(tool_name, arguments),
            name=f"mcp:{server_name}:{tool_name}",
        )
        self._active_calls.add(task)
        try:
            return await task
        finally:
            self._active_calls.discard(task)

    async def close(self) -> None:
        self._accepting = False
        active = tuple(self._active_calls)
        for task in active:
            task.cancel()
        if active:
            done, pending = await asyncio.wait(active, timeout=3)
            for task in pending:
                task.cancel()
        await asyncio.gather(*(session.close() for session in self.sessions.values()), return_exceptions=True)
