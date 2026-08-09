from __future__ import annotations

from dataclasses import dataclass

from prompt_toolkit import PromptSession

from artcode.tools import ToolPreview, ToolResult
from artcode.permissions import ApprovalChoice, ApprovalRequest
from artcode.mcp.models import McpServerConfig, McpStartupReport
from artcode.commands.base import DisplayMode
from artcode.runtime.state import RuntimeStatusSnapshot

from .keybindings import create_input_keybindings
from .render import TuiRenderer


class UserRequestedExit(Exception):
    pass


@dataclass
class PromptToolkitTui:
    renderer: TuiRenderer

    def __post_init__(self) -> None:
        self._display_mode = DisplayMode.DEFAULT
        self._session: PromptSession[str] = PromptSession(
            multiline=True,
            key_bindings=create_input_keybindings(),
            prompt_continuation="... ",
        )

    async def read_input(self, model: str) -> str:
        try:
            return await self._session.prompt_async(
                self.renderer.prompt_text(model, self._display_mode)
            )
        except (KeyboardInterrupt, EOFError) as exc:
            raise UserRequestedExit from exc

    def show_startup(self, status) -> None:
        self.renderer.show_startup(status)

    def show_mcp_startup(self, report: McpStartupReport) -> None:
        self.renderer.show_mcp_startup(report)

    def show_help(self, message: str) -> None:
        self.renderer.show_help(message)

    def show_error(self, error) -> None:
        self.renderer.show_error(error)

    def show_cancelled(self) -> None:
        self.renderer.show_cancelled()

    def show_exit(self) -> None:
        self.renderer.show_exit()

    def show_user_label(self) -> None:
        self.renderer.show_user_label(self._display_mode)

    def show_assistant_label(self) -> None:
        self.renderer.show_assistant_label(self._display_mode)

    def set_display_mode(self, mode: DisplayMode) -> None:
        self._display_mode = mode

    def clear_screen(self) -> None:
        self.renderer.clear_screen()

    def show_runtime_status(self, snapshot: RuntimeStatusSnapshot) -> None:
        self.renderer.show_runtime_status(snapshot)

    def stream_delta(self, text: str) -> None:
        self.renderer.stream_delta(text)

    def finish_assistant_message(self) -> None:
        self.renderer.finish_assistant_message()

    def show_tool_preview(self, preview: ToolPreview) -> None:
        self.renderer.show_tool_preview(preview)

    async def confirm_tool_execution(self, preview: ToolPreview) -> bool:
        while True:
            answer = await self._session.prompt_async("执行这个工具？(yes/no)> ")
            normalized = answer.strip().lower()
            if normalized in {"yes", "y"}:
                return True
            if normalized in {"no", "n"}:
                return False

    async def confirm_mcp_server(self, config: McpServerConfig) -> bool:
        self.renderer.show_mcp_server_approval(config)
        while True:
            answer = await self._session.prompt_async("连接这个项目 MCP Server？(yes/no)> ")
            if answer.strip().lower() in {"yes", "y"}:
                return True
            if answer.strip().lower() in {"no", "n"}:
                return False

    async def confirm_mcp_tool(self, preview: ToolPreview, plan_mode: bool) -> bool:
        self.renderer.show_mcp_tool_approval(preview, plan_mode)
        while True:
            answer = await self._session.prompt_async("执行这个 MCP 工具？(yes/no)> ")
            if answer.strip().lower() in {"yes", "y"}:
                return True
            if answer.strip().lower() in {"no", "n"}:
                return False

    async def request_approval(self, request: ApprovalRequest) -> ApprovalChoice:
        self.renderer.show_approval(request)
        choices = {
            "1": ApprovalChoice.ALLOW_ONCE,
            "2": ApprovalChoice.DENY_ONCE,
            "3": ApprovalChoice.ALLOW_ALWAYS,
            "4": ApprovalChoice.DENY_ALWAYS,
        }
        while True:
            answer = await self._session.prompt_async(
                "选择：1 仅本次允许 / 2 仅本次禁止 / 3 以后允许 / 4 以后禁止 > "
            )
            if answer.strip() in choices:
                return choices[answer.strip()]

    async def confirm_unsandboxed(self) -> bool:
        while True:
            answer = await self._session.prompt_async(
                "关闭 Seatbelt 将失去操作系统级隔离，确认继续？(yes/no)> "
            )
            normalized = answer.strip().lower()
            if normalized in {"yes", "y"}:
                return True
            if normalized in {"no", "n"}:
                return False

    def show_tool_result_summary(self, result: ToolResult) -> None:
        self.renderer.show_tool_result_summary(result)

    def show_agent_iteration(self, current: int, maximum: int | None) -> None:
        self.renderer.show_agent_iteration(current, maximum)

    def show_tool_calls_received(self, count: int) -> None:
        self.renderer.show_tool_calls_received(count)

    def show_tool_batch_started(self, batch_index: int, safety: str, count: int) -> None:
        self.renderer.show_tool_batch_started(batch_index, safety, count)

    def show_token_usage(
        self,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        total_tokens: int | None = None,
        cached_tokens: int | None = None,
        cache_miss_tokens: int | None = None,
    ) -> None:
        self.renderer.show_token_usage(prompt_tokens, completion_tokens, total_tokens, cached_tokens, cache_miss_tokens)

    def show_agent_stopped(self, reason: str, message: str = "") -> None:
        self.renderer.show_agent_stopped(reason, message)

    def show_context_status(self, payload: dict) -> None:
        self.renderer.show_context_status(payload)

    def show_persistence_status(self, payload: dict) -> None:
        self.renderer.show_persistence_status(payload)
