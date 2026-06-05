from __future__ import annotations

from dataclasses import dataclass

from prompt_toolkit import PromptSession

from .keybindings import create_input_keybindings
from .render import TuiRenderer


class UserRequestedExit(Exception):
    pass


@dataclass
class PromptToolkitTui:
    renderer: TuiRenderer

    def __post_init__(self) -> None:
        self._session: PromptSession[str] = PromptSession(
            multiline=True,
            key_bindings=create_input_keybindings(),
            prompt_continuation="... ",
        )

    async def read_input(self, model: str) -> str:
        try:
            return await self._session.prompt_async(self.renderer.prompt_text(model))
        except (KeyboardInterrupt, EOFError) as exc:
            raise UserRequestedExit from exc

    def show_startup(self, status) -> None:
        self.renderer.show_startup(status)

    def show_help(self, message: str) -> None:
        self.renderer.show_help(message)

    def show_error(self, error) -> None:
        self.renderer.show_error(error)

    def show_cancelled(self) -> None:
        self.renderer.show_cancelled()

    def show_exit(self) -> None:
        self.renderer.show_exit()

    def show_user_label(self) -> None:
        self.renderer.show_user_label()

    def show_assistant_label(self) -> None:
        self.renderer.show_assistant_label()

    def stream_delta(self, text: str) -> None:
        self.renderer.stream_delta(text)

    def finish_assistant_message(self) -> None:
        self.renderer.finish_assistant_message()
