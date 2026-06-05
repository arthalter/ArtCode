from __future__ import annotations

from typing import Protocol

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from artcode.config import SafeConfigStatus
from artcode.errors import ArtCodeError


class _PrintableError(Protocol):
    user_message: str


class TuiRenderer:
    def __init__(self, console: Console | None = None) -> None:
        self.console = console or Console()

    def show_startup(self, status: SafeConfigStatus) -> None:
        thinking = "on" if status.thinking_enabled else "off"
        if status.thinking_enabled:
            thinking = f"{thinking} ({status.thinking_effort})"
        body = "\n".join(
            [
                status.chapter,
                f"protocol: {status.protocol}",
                f"model: {status.model}",
                f"base_url: {status.base_url}",
                "streaming: on",
                f"thinking: {thinking}",
                f"api_key: {status.masked_api_key}",
                "input: Enter 发送，Ctrl+Enter 或 Esc Enter 换行",
            ]
        )
        self.console.print(Panel(body, title="ArtCode", border_style="cyan"))

    def prompt_text(self, model: str) -> str:
        return f"{model}> "

    def show_user_label(self) -> None:
        self.console.print(Text("User", style="bold green"))

    def show_assistant_label(self) -> None:
        self.console.print(Text("ArtCode", style="bold cyan"))

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
