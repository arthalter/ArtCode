from __future__ import annotations

from rich.console import Console

from artcode.tools import ToolPreview
from artcode.tui.app import PromptToolkitTui
from artcode.tui.render import TuiRenderer


class FakeSession:
    def __init__(self, answers: list[str]) -> None:
        self.answers = answers

    async def prompt_async(self, prompt: str) -> str:
        return self.answers.pop(0)


def tui_with_answers(answers: list[str]) -> PromptToolkitTui:
    tui = PromptToolkitTui(TuiRenderer(Console(record=True)))
    tui._session = FakeSession(answers)
    return tui


async def test_confirm_tool_execution_accepts_yes_and_y() -> None:
    preview = ToolPreview("write_file", "写入", "note.txt", True)

    assert await tui_with_answers(["yes"]).confirm_tool_execution(preview) is True
    assert await tui_with_answers(["y"]).confirm_tool_execution(preview) is True


async def test_confirm_tool_execution_accepts_no_and_n() -> None:
    preview = ToolPreview("write_file", "写入", "note.txt", True)

    assert await tui_with_answers(["no"]).confirm_tool_execution(preview) is False
    assert await tui_with_answers(["n"]).confirm_tool_execution(preview) is False


async def test_confirm_tool_execution_reprompts_invalid_answer() -> None:
    preview = ToolPreview("write_file", "写入", "note.txt", True)

    assert await tui_with_answers(["maybe", "y"]).confirm_tool_execution(preview) is True
