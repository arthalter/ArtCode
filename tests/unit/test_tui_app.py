from __future__ import annotations

from pathlib import Path

import pytest
from rich.console import Console

from artcode.tools import ToolPreview
from artcode.commands import DisplayMode
from artcode.runtime.state import RuntimeStatusSnapshot
from artcode.agent import TokenUsage
from artcode.permissions import ApprovalChoice, ApprovalRequest, PermissionMode, ShellPolicy
from artcode.tui.app import PromptToolkitTui
from artcode.tui.render import TuiRenderer


class FakeSession:
    def __init__(self, answers: list[str]) -> None:
        self.answers = answers
        self.prompts: list[str] = []

    async def prompt_async(self, prompt: str) -> str:
        self.prompts.append(prompt)
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


async def test_display_mode_controls_prompt_and_labels() -> None:
    tui = tui_with_answers(["任务"])
    tui.set_display_mode(DisplayMode.PLAN)

    assert await tui.read_input("deepseek") == "任务"
    tui.show_user_label()
    tui.show_assistant_label()

    assert tui._session.prompts == ["[PLAN] deepseek > "]
    output = tui.renderer.console.export_text()
    assert "[PLAN] User" in output
    assert "[PLAN] ArtCode" in output


def test_clear_and_status_forward_to_renderer() -> None:
    tui = PromptToolkitTui(TuiRenderer(Console(record=True)))
    session_before = tui._session
    snapshot = RuntimeStatusSnapshot(
        model="deepseek",
        workspace="/tmp/workspace",
        display_mode=DisplayMode.DEFAULT,
        permission_mode="default",
        shell_policy="auto",
        seatbelt_status="self-test passed",
        session_id="session-1",
        session_state="new",
        estimated_context_tokens=123,
        context_window_tokens=200_000,
        last_token_usage=TokenUsage(total_tokens=12),
    )

    tui.clear_screen()
    tui.show_runtime_status(snapshot)

    assert tui._session is session_before
    assert tui._session.completer is None
    output = tui.renderer.console.export_text()
    assert "运行状态" in output
    assert "session-1" in output
    assert "total=12" in output


@pytest.mark.ch10_5
@pytest.mark.parametrize("plan_mode", [False, True])
async def test_mcp_confirmation_receives_explicit_plan_mode(plan_mode: bool) -> None:
    tui = tui_with_answers(["yes"])
    preview = ToolPreview("mcp__s__t", "{}", "s/t", True)

    assert await tui.confirm_mcp_tool(preview, plan_mode)
    assert f"Plan 模式：{'是' if plan_mode else '否'}" in tui.renderer.console.export_text()


@pytest.mark.ch10_5
@pytest.mark.parametrize(("answer", "expected"), [("yes", True), ("no", False)])
async def test_unsandboxed_confirmation_is_explicit(answer: str, expected: bool) -> None:
    assert await tui_with_answers([answer]).confirm_unsandboxed() is expected


@pytest.mark.ch10_5
async def test_permission_approval_maps_all_four_stable_choices() -> None:
    request = ApprovalRequest(
        "write_file",
        "note.txt",
        Path("/tmp/workspace"),
        PermissionMode.DEFAULT,
        ShellPolicy.SANDBOX_AUTO,
        "rule",
    )
    expected = [
        ApprovalChoice.ALLOW_ONCE,
        ApprovalChoice.DENY_ONCE,
        ApprovalChoice.ALLOW_ALWAYS,
        ApprovalChoice.DENY_ALWAYS,
    ]
    for answer, choice in zip(("1", "2", "3", "4"), expected, strict=True):
        assert await tui_with_answers([answer]).request_approval(request) is choice
