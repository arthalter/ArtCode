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


def test_agent_progress_methods_forward_to_renderer() -> None:
    tui = PromptToolkitTui(TuiRenderer(Console(record=True)))

    tui.show_agent_iteration(1, 12)
    tui.show_tool_calls_received(2)
    tui.show_tool_batch_started(1, "side_effect", 1)
    tui.show_token_usage(1, 2, 3)
    tui.show_agent_stopped("natural")

    output = tui.renderer.console.export_text()
    assert "第 1/12 轮" in output
    assert "2 个工具调用" in output
    assert "side_effect" in output
    assert "total=3" in output
    assert "natural" in output
