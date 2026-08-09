from __future__ import annotations

from typing import Protocol

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from artcode.errors import ArtCodeError
from artcode.tools import ToolPreview, ToolResult
from artcode.permissions import ApprovalRequest
from artcode.mcp.models import McpServerConfig, McpStartupReport, TransportKind
from artcode.commands.base import DisplayMode
from artcode.runtime.state import RuntimeStatusSnapshot, StartupStatusSnapshot


class _PrintableError(Protocol):
    user_message: str


class TuiRenderer:
    def __init__(self, console: Console | None = None) -> None:
        self.console = console or Console()

    def show_startup(self, status: StartupStatusSnapshot) -> None:
        thinking = "on" if status.thinking_enabled else "off"
        if status.thinking_enabled:
            thinking = f"{thinking} (high)"
        body = "\n".join(
            [
                f"protocol: {status.protocol}",
                f"model: {status.model}",
                f"base_url: {status.base_url}",
                "streaming: on",
                f"thinking: {thinking}",
                f"api_key: {'configured' if status.api_key_configured else 'missing'}",
                f"workspace: {status.workspace}",
                f"permission: {status.permission_mode}",
                f"sandbox: {status.shell_policy}",
                f"seatbelt: {status.seatbelt_status}",
                f"context: {status.context_window_tokens} tokens",
                f"session: {status.session_id or 'disabled'} ({status.session_state})",
                f"recovered: {status.recovered_messages} messages; bad lines: {status.bad_session_lines}; truncated: {'yes' if status.session_truncated else 'no'}",
                f"instructions: {status.instruction_bytes} bytes; issues: {status.instruction_issues}",
                f"memory: user={status.user_active_notes}; project={status.project_active_notes}",
                "input: Enter 发送，Ctrl+Enter 或 Esc Enter 换行",
            ]
        )
        self.console.print(Panel(body, title="ArtCode", border_style="cyan"))

    def show_approval(self, request: ApprovalRequest) -> None:
        body = "\n".join(
            [
                f"工具：{request.tool_name}",
                f"目标：{request.target}",
                f"Workspace：{request.workspace}",
                f"权限模式：{request.permission_mode.value}",
                f"Shell 策略：{request.shell_policy.value}",
                f"ASK 来源：{request.source}",
            ]
        )
        self.console.print(Panel(body, title="需要授权", border_style="yellow"))

    def show_mcp_server_approval(self, config: McpServerConfig) -> None:
        if config.transport is TransportKind.STDIO:
            target = " ".join((config.command or "", *config.args))
            risk = "外部进程不受 ArtCode Workspace 文件沙箱保护。"
            names = f"环境变量：{', '.join(config.referenced_variables) or '无'}"
        else:
            target = config.url or ""
            risk = "跨域重定向会原样转发全部自定义 Headers。"
            names = f"Headers：{', '.join(config.headers) or '无'}；引用变量：{', '.join(config.referenced_variables) or '无'}"
        body = "\n".join((f"Server：{config.name}", f"目标：{target}", names, risk))
        self.console.print(Panel(body, title="项目 MCP Server 授权", border_style="yellow"))

    def show_mcp_tool_approval(self, preview: ToolPreview, plan_mode: bool = False) -> None:
        body = "\n".join(
            (
                f"来源：{preview.target}",
                f"注册名：{preview.tool_name}",
                f"Plan 模式：{'是' if plan_mode else '否'}",
                f"脱敏参数：{preview.summary}",
                "MCP 工具始终视为可能产生副作用。",
            )
        )
        self.console.print(Panel(body, title="MCP 工具授权", border_style="yellow"))

    def show_mcp_startup(self, report: McpStartupReport) -> None:
        lines = [
            f"配置 {report.configured_count} / 成功 {report.connected_count} / "
            f"失败 {report.failed_count} / 工具 {report.registered_tool_count}"
        ]
        for item in report.server_reports:
            suffix = f"：{item.detail}" if item.detail else ""
            lines.append(f"{item.name} [{item.source.value}] {item.state.value} 工具={item.tool_count}{suffix}")
        self.console.print(Panel("\n".join(lines), title="MCP", border_style="magenta"))

    def prompt_text(
        self,
        model: str,
        mode: DisplayMode = DisplayMode.DEFAULT,
    ) -> str:
        return f"[{mode.value}] {model} > "

    def show_user_label(self, mode: DisplayMode = DisplayMode.DEFAULT) -> None:
        self.console.print(Text(f"[{mode.value}] User", style="bold green"))

    def show_assistant_label(self, mode: DisplayMode = DisplayMode.DEFAULT) -> None:
        self.console.print(Text(f"[{mode.value}] ArtCode", style="bold cyan"))

    def clear_screen(self) -> None:
        self.console.clear()

    def show_runtime_status(self, snapshot: RuntimeStatusSnapshot) -> None:
        usage = snapshot.last_token_usage
        usage_text = "不可用"
        if usage is not None:
            usage_text = (
                f"prompt={_available(usage.prompt_tokens)} "
                f"completion={_available(usage.completion_tokens)} "
                f"total={_available(usage.total_tokens)} "
                f"cached={_available(usage.cached_tokens)} "
                f"miss={_available(usage.cache_miss_tokens)}"
            )
        body = "\n".join(
            (
                f"模型：{snapshot.model}",
                f"Workspace：{snapshot.workspace or '不可用'}",
                f"显示模式：{snapshot.display_mode.value}",
                f"权限模式：{snapshot.permission_mode}",
                f"Shell 策略：{snapshot.shell_policy}",
                f"Seatbelt：{snapshot.seatbelt_status}",
                f"会话 ID：{snapshot.session_id or '不可用'}",
                f"会话状态：{snapshot.session_state}",
                f"当前上下文估算：{_available(snapshot.estimated_context_tokens)}",
                f"上下文窗口上限：{snapshot.context_window_tokens}",
                f"最近 Token 用量：{usage_text}",
            )
        )
        self.console.print(Panel(body, title="运行状态", border_style="cyan"))

    def stream_delta(self, text: str) -> None:
        self.console.print(text, end="", markup=False, highlight=False, soft_wrap=True)

    def finish_assistant_message(self) -> None:
        self.console.print()

    def show_help(self, message: str) -> None:
        self.console.print(message, style="cyan")

    def show_error(self, error: _PrintableError | ArtCodeError) -> None:
        self.console.print(f"错误：{error.user_message}", style="bold red")

    def show_startup_error(self, error: _PrintableError | ArtCodeError) -> None:
        self.console.print(f"启动失败：{error.user_message}", style="bold red")

    def show_cancelled(self) -> None:
        self.console.print("\n已取消当前回复，本轮半截回复未写入上下文。", style="yellow")

    def show_exit(self) -> None:
        self.console.print("已退出 ArtCode。", style="cyan")

    def show_tool_preview(self, preview: ToolPreview) -> None:
        self.console.print(f"准备调用工具：{preview.tool_name}", style="bold yellow")
        self.console.print(f"摘要：{preview.summary}", style="yellow")
        self.console.print(f"影响目标：{preview.target}", style="yellow")

    def show_tool_result_summary(self, result: ToolResult) -> None:
        status = "成功" if result.ok else "失败"
        detail = f"工具执行{status}：{result.message}（返回 {result.bytes_returned} bytes）"
        style = "green" if result.ok else "red"
        self.console.print(detail, style=style)

    def show_agent_iteration(self, current: int, maximum: int | None) -> None:
        label = f"第 {current} 轮" if maximum is None else f"第 {current}/{maximum} 轮"
        self.console.print(f"Agent Loop：{label}", style="cyan")

    def show_tool_calls_received(self, count: int) -> None:
        self.console.print(f"模型请求 {count} 个工具调用。", style="yellow")

    def show_tool_batch_started(self, batch_index: int, safety: str, count: int) -> None:
        self.console.print(f"执行工具批次 {batch_index}：{safety}，{count} 个工具", style="yellow")

    def show_token_usage(
        self,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        total_tokens: int | None = None,
        cached_tokens: int | None = None,
        cache_miss_tokens: int | None = None,
    ) -> None:
        cache_part = ""
        if cached_tokens is not None or cache_miss_tokens is not None:
            cache_part = f" cached={cached_tokens} miss={cache_miss_tokens}"
        self.console.print(
            f"Token 用量：prompt={prompt_tokens} completion={completion_tokens} total={total_tokens}{cache_part}",
            style="cyan",
        )

    def show_agent_stopped(self, reason: str, message: str = "") -> None:
        suffix = f"：{message}" if message else ""
        self.console.print(f"Agent Loop 停止（{reason}）{suffix}", style="cyan")

    def show_context_status(self, payload: dict) -> None:
        circuit = "open" if payload.get("circuit_open") else "closed"
        message = f"；{payload['message']}" if payload.get("message") else ""
        detail = (
            f"上下文：{payload.get('trigger')} / {payload.get('status')}，"
            f"{payload.get('before_tokens')} → {payload.get('after_tokens')} Token，"
            f"存盘 {payload.get('persisted_count')} 个，熔断 {circuit}{message}"
        )
        style = "red" if payload.get("status") in {"failed", "blocked"} else "cyan"
        self.console.print(detail, style=style)

    def show_persistence_status(self, payload: dict) -> None:
        kind = payload.get("kind", "persistence")
        status = payload.get("status", "unknown")
        message = payload.get("message", "")
        counts = ""
        if kind == "memory":
            counts = (
                f" 新增={payload.get('created', 0)} 更新={payload.get('updated', 0)} "
                f"作废={payload.get('superseded', 0)} 拒绝={payload.get('rejected', 0)}"
            )
        suffix = f"：{message}" if message else ""
        style = "red" if status in {"failed", "rejected"} else "cyan"
        self.console.print(f"持久状态 [{kind}/{status}]{counts}{suffix}", style=style)


def _available(value: int | None) -> str:
    return str(value) if value is not None else "不可用"
