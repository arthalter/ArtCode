from __future__ import annotations

from dataclasses import dataclass
import asyncio
import inspect
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from prompt_toolkit import PromptSession
from prompt_toolkit.keys import Keys

from artcode.tools import ToolPreview, ToolResult
from artcode.permissions import ApprovalChoice, ApprovalRequest
from artcode.mcp.models import McpServerConfig, McpStartupReport
from artcode.commands.base import DisplayMode

if TYPE_CHECKING:
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
        self._generation_input_task: asyncio.Task[None] | None = None
        self._generation_callbacks = None

    async def read_input(self, model: str) -> str:
        try:
            return await self._session.prompt_async(
                self.renderer.prompt_text(model, self._display_mode)
            )
        except (KeyboardInterrupt, EOFError) as exc:
            raise UserRequestedExit from exc

    def begin_generation_controls(self, on_cancel, on_background) -> None:
        self._generation_callbacks = (on_cancel, on_background)
        if self._generation_input_task is not None:
            self._generation_input_task.cancel()
        self._generation_input_task = asyncio.create_task(
            self._watch_generation_input(on_cancel, on_background),
            name="artcode-generation-input",
        )

    async def end_generation_controls(self) -> None:
        self._generation_callbacks = None
        await self._stop_generation_controls()

    async def _stop_generation_controls(self) -> None:
        task = self._generation_input_task
        self._generation_input_task = None
        if task is None:
            return
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    @asynccontextmanager
    async def _generation_controls_paused(self):
        callbacks = self._generation_callbacks
        if callbacks is not None:
            await self._stop_generation_controls()
        try:
            yield
        finally:
            if callbacks is not None and self._generation_callbacks is callbacks:
                self.begin_generation_controls(*callbacks)

    async def _watch_generation_input(self, on_cancel, on_background) -> None:
        input_port = self._session.app.input
        ready = asyncio.Event()

        def keys_ready() -> None:
            ready.set()

        try:
            with input_port.raw_mode(), input_port.attach(keys_ready):
                while True:
                    await ready.wait()
                    ready.clear()
                    for key_press in input_port.read_keys():
                        if key_press.key == Keys.ControlB:
                            result = on_background()
                        elif key_press.key == Keys.ControlC:
                            result = on_cancel()
                        else:
                            continue
                        if inspect.isawaitable(result):
                            await result
        except asyncio.CancelledError:
            raise
        except (EOFError, OSError, RuntimeError):
            # Signal handlers remain the fallback on unsupported terminals.
            return

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
        async with self._generation_controls_paused():
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
        async with self._generation_controls_paused():
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
        async with self._generation_controls_paused():
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

    async def confirm_worktree_discard(
        self,
        task_id: str,
        path,
        branch: str,
        status,
    ) -> bool:
        lines = [
            "危险操作：以下 Worktree 含尚未安全交接的成果，丢弃将永久删除：",
            f"任务：{task_id}",
            f"路径：{path}",
            f"分支：{branch}",
            (
                f"已跟踪修改：{status.tracked_changes}；暂存修改：{status.staged_changes}；"
                f"未跟踪文件：{status.untracked_changes}；相对基准新增提交：{status.commits_ahead}"
            ),
            "此操作不可恢复，且不会影响主工作区或其他 Worktree。",
        ]
        self.renderer.show_help("\n".join(lines))
        while True:
            answer = await self._session.prompt_async(
                "确认丢弃这些成果？(yes/no)> "
            )
            normalized = answer.strip().lower()
            if normalized in {"yes", "y"}:
                return True
            if normalized in {"no", "n"}:
                return False

    async def choose_active_task_exit(self, summaries) -> str:
        lines = ["仍有活动子 Agent 任务："]
        for item in summaries:
            lines.append(
                f"{item.task_id} | {item.status.value} | "
                f"{item.kind} | worktree={item.worktree_path or '尚未创建'}"
            )
        lines.append("退出前请选择如何处理这些任务。")
        self.renderer.show_help("\n".join(lines))
        choices = {"1": "wait", "2": "cancel", "3": "return"}
        try:
            while True:
                answer = await self._session.prompt_async(
                    "选择：1 等待全部完成 / 2 取消后退出 / 3 返回 ArtCode > "
                )
                selected = choices.get(answer.strip())
                if selected is not None:
                    return selected
        except (KeyboardInterrupt, EOFError):
            # A closed terminal cannot return to the UI; cancellation still
            # executes each task's normal Worktree protection path.
            return "cancel"

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
