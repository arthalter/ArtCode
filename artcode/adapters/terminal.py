from __future__ import annotations

from dataclasses import asdict, is_dataclass
import asyncio
import json

from prompt_toolkit import PromptSession
from prompt_toolkit.input import create_input
from prompt_toolkit.keys import Keys
from rich.console import Console

from artcode.core.application import (
    Application,
    ClearDisplay,
    ErrorOutput,
    ExitRequested,
    RunStopped,
    StateOutput,
    TextOutput,
)
from artcode.core.tool import ApprovalChoice, ApprovalRequest
from artcode.core.workspace import WorktreeHandoff


class TerminalAdapter:
    def __init__(
        self,
        *,
        prompt: PromptSession | None = None,
        console: Console | None = None,
    ) -> None:
        self.input = create_input() if prompt is None else None
        self.prompt = prompt or PromptSession(multiline=True, input=self.input)
        self.console = console or Console()

    async def read(self) -> str:
        return await self.prompt.prompt_async("artcode> ")

    def render(self, event) -> None:
        if isinstance(event, TextOutput):
            self.console.print(event.text, end="" if event.streaming else "\n")
        elif isinstance(event, ErrorOutput):
            self.console.print(f"[red]{event.message}[/red]")
        elif isinstance(event, StateOutput):
            value = asdict(event.value) if is_dataclass(event.value) else event.value
            self.console.print(json.dumps(value, ensure_ascii=False, default=str, indent=2))
        elif isinstance(event, RunStopped):
            self.console.print(f"\n[dim]stopped: {event.reason} ({event.rounds} rounds)[/dim]")
        elif isinstance(event, ClearDisplay):
            self.console.clear()

    async def approve(self, request: ApprovalRequest) -> ApprovalChoice:
        answer = (
            await self.prompt.prompt_async(
                f"允许 {request.tool_name} 作用于 {request.target}? "
                "[y]本次允许/[n]本次拒绝/[a]以后允许/[d]以后拒绝: "
            )
        ).strip().casefold()
        return {
            "y": ApprovalChoice.ALLOW_ONCE,
            "a": ApprovalChoice.ALLOW_ALWAYS,
            "d": ApprovalChoice.DENY_ALWAYS,
        }.get(answer, ApprovalChoice.DENY_ONCE)

    async def approve_mcp_server(self, name: str, summary: str) -> bool:
        answer = await self.prompt.prompt_async(
            f"项目请求启动 MCP Server {name} ({summary})，是否允许? [y/N]: "
        )
        return answer.strip().casefold() in {"y", "yes"}

    async def confirm_worktree_discard(self, handoff: WorktreeHandoff) -> bool:
        answer = await self.prompt.prompt_async(
            "不可恢复地丢弃 Worktree "
            f"{handoff.path}（未提交 {handoff.tracked_changes + handoff.staged_changes + handoff.untracked_changes}，"
            f"新增提交 {handoff.commits_ahead}）? 输入 discard 确认: "
        )
        return answer.strip() == "discard"

    async def choose_active_task_exit(self, tasks) -> str:
        self.console.print("仍有活动 Task：" + "、".join(task.id for task in tasks))
        answer = await self.prompt.prompt_async(
            "[w]等待全部完成 / [c]取消后退出 / [r]返回 ArtCode: "
        )
        return {"w": "wait", "c": "cancel"}.get(answer.strip().casefold(), "return")

    async def monitor_controls(self, application: Application, stop: asyncio.Event) -> None:
        if self.input is None or self.input.closed:
            await stop.wait()
            return
        ready = asyncio.Event()

        def input_ready() -> None:
            ready.set()

        with self.input.raw_mode(), self.input.attach(input_ready):
            while not stop.is_set():
                ready_task = asyncio.create_task(ready.wait())
                stop_task = asyncio.create_task(stop.wait())
                done, _ = await asyncio.wait(
                    (ready_task, stop_task), return_when=asyncio.FIRST_COMPLETED
                )
                for task in (ready_task, stop_task):
                    if task not in done:
                        task.cancel()
                await asyncio.gather(ready_task, stop_task, return_exceptions=True)
                if stop.is_set():
                    return
                ready.clear()
                for key_press in self.input.read_keys():
                    if key_press.key == Keys.ControlB:
                        if application.background_current_task():
                            self.console.print("\n[dim]Task 已转入后台。[/dim]")
                    elif key_press.key == Keys.ControlC:
                        application.cancel_current()


async def run_terminal(application: Application, terminal: TerminalAdapter) -> int:
    try:
        while True:
            try:
                text = await terminal.read()
            except EOFError:
                return 0
            except KeyboardInterrupt:
                if application.cancel_current():
                    continue
                return 130
            stop = asyncio.Event()
            monitor = asyncio.create_task(terminal.monitor_controls(application, stop))
            try:
                async for event in application.stream(text):
                    terminal.render(event)
                    if isinstance(event, ExitRequested):
                        return event.code
            finally:
                stop.set()
                await asyncio.gather(monitor, return_exceptions=True)
    finally:
        await application.close()
