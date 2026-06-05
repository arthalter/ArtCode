from __future__ import annotations

import asyncio
import signal
from dataclasses import dataclass, field
from typing import Protocol

from artcode.commands import CommandRegistry, create_default_registry
from artcode.config import ArtCodeConfig
from artcode.conversation import ConversationContext
from artcode.errors import RequestError
from artcode.providers.base import StreamingProvider
from artcode.providers.events import CONTENT_DELTA, DONE
from artcode.tui import UserRequestedExit


class TuiApp(Protocol):
    def show_startup(self, status) -> None:
        ...

    async def read_input(self, model: str) -> str:
        ...

    def show_help(self, message: str) -> None:
        ...

    def show_error(self, error) -> None:
        ...

    def show_cancelled(self) -> None:
        ...

    def show_exit(self) -> None:
        ...

    def show_user_label(self) -> None:
        ...

    def show_assistant_label(self) -> None:
        ...

    def stream_delta(self, text: str) -> None:
        ...

    def finish_assistant_message(self) -> None:
        ...


@dataclass
class ArtCodeRuntime:
    config: ArtCodeConfig
    provider: StreamingProvider
    conversation: ConversationContext
    tui: TuiApp
    commands: CommandRegistry = field(default_factory=create_default_registry)

    async def run(self) -> int:
        self.tui.show_startup(self.config.safe_status())
        while True:
            try:
                user_input = await self.tui.read_input(self.config.model)
            except UserRequestedExit:
                self.tui.show_exit()
                return 0

            if not user_input.strip():
                continue

            command_result = self.commands.handle(user_input)
            if command_result is not None:
                if command_result.message:
                    self.tui.show_help(command_result.message)
                if command_result.should_exit:
                    self.tui.show_exit()
                    return 0
                continue

            self.tui.show_user_label()
            self.conversation.append_user(user_input)
            self.tui.show_assistant_label()

            result = await self._generate_assistant_reply()
            if result is None:
                self.tui.show_cancelled()
                continue
            if result:
                self.conversation.append_assistant(result)

    async def _generate_assistant_reply(self) -> str | None:
        messages = self.conversation.export_messages()
        task = asyncio.create_task(self._consume_provider_stream(messages))
        self._install_generation_cancel_handler(task)
        try:
            return await task
        except asyncio.CancelledError:
            return None
        except RequestError as exc:
            self.tui.show_error(exc)
            return ""
        finally:
            self._remove_generation_cancel_handler()

    async def _consume_provider_stream(self, messages: list[dict[str, str]]) -> str:
        parts: list[str] = []
        async for event in self.provider.stream_chat(messages):
            event_type = event.get("type")
            if event_type == CONTENT_DELTA:
                text = event.get("text", "")
                parts.append(text)
                self.tui.stream_delta(text)
            elif event_type == DONE:
                self.tui.finish_assistant_message()
                return "".join(parts)
        return "".join(parts)

    def _install_generation_cancel_handler(self, task: asyncio.Task[str]) -> None:
        try:
            loop = asyncio.get_running_loop()
            loop.add_signal_handler(signal.SIGINT, task.cancel)
        except (NotImplementedError, RuntimeError):
            return

    def _remove_generation_cancel_handler(self) -> None:
        try:
            loop = asyncio.get_running_loop()
            loop.remove_signal_handler(signal.SIGINT)
        except (NotImplementedError, RuntimeError):
            return
