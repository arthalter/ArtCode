from __future__ import annotations

import asyncio
from dataclasses import replace
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
        self._started = False
        self._closed = False
        self._registered_registry: Any | None = None
        self._close_task: asyncio.Task[None] | None = None

    async def start(self) -> McpStartupReport:
        if self._closed:
            raise RuntimeError("已经关闭的 MCP Manager 不能重新启动。")
        if self._started:
            return self.report
        semaphore = asyncio.Semaphore(5)

        async def start_one(config: McpServerConfig):
            async with semaphore:
                return await self._start_one(config)

        outcomes = await asyncio.gather(*(start_one(config) for config in self.configs))
        issue_reports = [
            McpServerReport(
                issue.server_name, issue.source, ServerState.INVALID,
                failure_stage=FailureStage.CONFIG, detail=issue.message,
            )
            for issue in self.issues
        ]
        reports: list[McpServerReport] = []
        adapter_items: list[Any] = []
        registered_names: dict[str, str] = {}
        for report, adapters, local_issues in outcomes:
            registration_issues = list(local_issues)
            accepted = 0
            for adapter in adapters:
                owner = registered_names.get(adapter.name)
                if owner is not None:
                    registration_issues.append(
                        f"{adapter.name}：与 Server {owner} 的注册名冲突，已跳过。"
                    )
                    continue
                registered_names[adapter.name] = adapter.server_name
                adapter_items.append(adapter)
                accepted += 1
            reports.append(_with_registration(report, accepted, registration_issues))
        self.adapters = tuple(adapter_items)
        self.report = McpStartupReport(
            configured_count=len(self.configs) + len(self.issues),
            server_reports=tuple([*issue_reports, *reports]),
            registered_tool_count=len(self.adapters),
        )
        self._started = True
        return self.report

    async def _start_one(self, config: McpServerConfig):
        if not config.enabled:
            return McpServerReport(config.name, config.source, ServerState.DISABLED), (), ()
        if config.source is ServerSource.PROJECT:
            if self.approver is None:
                return McpServerReport(config.name, config.source, ServerState.REJECTED), (), ()
            try:
                approved = await self.approver(config)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                secrets = tuple(config.env.values()) + tuple(config.headers.values())
                return McpServerReport(
                    config.name,
                    config.source,
                    ServerState.UNAVAILABLE,
                    failure_stage=FailureStage.APPROVAL,
                    detail=sanitize_external_text(str(exc), secrets),
                ), (), ()
            if not approved:
                return McpServerReport(config.name, config.source, ServerState.REJECTED), (), ()
        try:
            expanded = expand_config(config)
        except ValueError as exc:
            return McpServerReport(
                config.name, config.source, ServerState.INVALID,
                failure_stage=FailureStage.CONFIG, detail=str(exc),
            ), (), ()
        session = McpSession(expanded, self.workspace)
        try:
            tools = await session.connect()
        except Exception as exc:
            secrets = tuple(expanded.env.values()) + tuple(expanded.headers.values())
            return McpServerReport(
                config.name, config.source, ServerState.UNAVAILABLE,
                failure_stage=FailureStage.INITIALIZE,
                detail=sanitize_external_text(str(exc), secrets),
            ), (), ()
        self.sessions[config.name] = session
        adapters: list[Any] = []
        used: set[str] = set()
        registration_issues: list[str] = []
        for tool in tools:
            try:
                adapter = create_adapter(self, config.name, tool)
                if adapter.name in used:
                    registration_issues.append(
                        f"{adapter.name}：同一 Server 内注册名重复，已跳过。"
                    )
                    continue
                used.add(adapter.name)
                adapters.append(adapter)
            except ValueError as exc:
                remote_name = sanitize_external_text(str(getattr(tool, "name", "<unknown>")))
                registration_issues.append(
                    f"{remote_name}：{sanitize_external_text(str(exc))}"
                )
                continue
        return McpServerReport(
            config.name, config.source, ServerState.READY,
            tool_count=len(adapters), truncated=session.truncated,
        ), tuple(adapters), tuple(registration_issues)

    def register_into(self, registry: Any) -> tuple[str, ...]:
        """Register discovered adapters while keeping conflicts observable."""

        if not self._started:
            raise RuntimeError("MCP Manager 尚未启动。")
        if self._registered_registry is registry:
            return ()
        if self._registered_registry is not None:
            raise RuntimeError("MCP 工具已经注册到另一个 ToolRegistry。")

        conflicts: dict[str, list[str]] = {}
        accepted: list[Any] = []
        for adapter in self.adapters:
            try:
                registry.register(adapter)
            except (TypeError, ValueError) as exc:
                conflicts.setdefault(adapter.server_name, []).append(
                    sanitize_external_text(f"{adapter.name}：{exc}")
                )
            else:
                accepted.append(adapter)
        if conflicts:
            reports = []
            for report in self.report.server_reports:
                issues = conflicts.get(report.name, ())
                reports.append(
                    _with_registration(
                        report,
                        report.tool_count - len(issues),
                        [*report.registration_issues, *issues],
                    )
                    if issues
                    else report
                )
            self.report = replace(
                self.report,
                server_reports=tuple(reports),
                registered_tool_count=len(accepted),
            )
        self.adapters = tuple(accepted)
        self._registered_registry = registry
        return tuple(issue for issues in conflicts.values() for issue in issues)

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
        if self._closed:
            return
        if self._close_task is None:
            self._close_task = asyncio.create_task(
                self._close_impl(), name="mcp-manager-close"
            )
        try:
            await asyncio.shield(self._close_task)
        except asyncio.CancelledError:
            await asyncio.shield(self._close_task)
            raise

    async def _close_impl(self) -> None:
        active = tuple(self._active_calls)
        for task in active:
            task.cancel()
        if active:
            await asyncio.gather(*active, return_exceptions=True)
        await asyncio.gather(
            *(session.close() for session in self.sessions.values()),
            return_exceptions=True,
        )
        self._closed = True


def _with_registration(
    report: McpServerReport,
    accepted_count: int,
    issues: list[str] | tuple[str, ...],
) -> McpServerReport:
    normalized = tuple(dict.fromkeys(issue for issue in issues if issue))
    if not normalized:
        return replace(report, tool_count=max(accepted_count, 0))
    detail = "；".join(normalized)
    return replace(
        report,
        tool_count=max(accepted_count, 0),
        failure_stage=FailureStage.REGISTRATION,
        detail=sanitize_external_text(detail, limit=1_000),
        registration_issues=normalized,
    )
