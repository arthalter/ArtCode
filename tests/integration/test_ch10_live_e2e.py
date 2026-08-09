from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

pytestmark = pytest.mark.live

from artcode.config import ArtCodeConfig, ConfigError, load_config
from artcode.conversation import ConversationContext
from artcode.providers.openai_compatible import OpenAICompatibleProvider
from artcode.runtime import ArtCodeRuntime
from artcode.permissions import ApprovalChoice


ROOT = Path(__file__).resolve().parents[2]


def required_live_config(workspace: Path) -> ArtCodeConfig:
    try:
        config = load_config(ROOT / "artcode.yaml")
    except ConfigError as exc:
        pytest.fail(f"ch10 live validation requires real API config: {exc.message}")
    if "your-deepseek-api-key" in config.api_key or config.api_key.startswith("<"):
        pytest.fail("ch10 live validation requires a real API key in artcode.yaml")
    return replace(config, model="deepseek-v4-flash", workspace=workspace)


class LiveTui:
    def __init__(self, inputs: list[str]) -> None:
        self.inputs = inputs
        self.modes = []
        self.statuses = []
        self.output: list[str] = []

    async def read_input(self, model: str) -> str:
        return self.inputs.pop(0)

    def show_startup(self, status) -> None:
        pass

    def show_help(self, message: str) -> None:
        self.output.append(message)

    def show_error(self, error) -> None:
        self.output.append(error.user_message)

    def show_cancelled(self) -> None:
        self.output.append("cancelled")

    def show_exit(self) -> None:
        pass

    def show_user_label(self) -> None:
        pass

    def show_assistant_label(self) -> None:
        pass

    def stream_delta(self, text: str) -> None:
        pass

    def finish_assistant_message(self) -> None:
        pass

    def show_tool_preview(self, preview) -> None:
        pass

    async def confirm_tool_execution(self, preview) -> bool:
        return True

    async def request_approval(self, request):
        return ApprovalChoice.ALLOW_ONCE

    async def confirm_mcp_tool(self, preview, plan_mode: bool) -> bool:
        return True

    async def confirm_unsandboxed(self) -> bool:
        return True

    def show_tool_result_summary(self, result) -> None:
        pass

    def show_agent_iteration(self, current: int, maximum: int) -> None:
        pass

    def show_tool_calls_received(self, count: int) -> None:
        pass

    def show_tool_batch_started(self, batch_index: int, safety: str, count: int) -> None:
        pass

    def show_token_usage(self, *values) -> None:
        pass

    def show_agent_stopped(self, reason: str, message: str = "") -> None:
        self.output.append(reason)

    def show_context_status(self, payload: dict) -> None:
        pass

    def show_persistence_status(self, payload: dict) -> None:
        pass

    def set_display_mode(self, mode) -> None:
        self.modes.append(mode)

    def clear_screen(self) -> None:
        pass

    def show_runtime_status(self, snapshot) -> None:
        self.statuses.append(snapshot)


async def test_live_deepseek_plan_do_keeps_command_routing_and_creates_file(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    marker = "CH10_LIVE_COMMAND_OK_8642"
    config = required_live_config(workspace)
    tui = LiveTui(
        [
            (
                "/plan 规划一个极小任务：在当前 Workspace 新建 ch10_live.txt，"
                f"文件内容必须恰好为 {marker} 加一个换行。"
                "只输出可执行计划，不要声称已经完成。"
            ),
            (
                "/do 必须实际调用 write_file 创建 ch10_live.txt；"
                f"内容必须恰好是 {marker} 加一个换行。完成后简短确认。"
            ),
            "/status",
            "/exit",
        ]
    )
    context = ConversationContext()
    runtime = ArtCodeRuntime(
        config,
        OpenAICompatibleProvider(config),
        context,
        tui,
    )

    assert await runtime.run() == 0

    target = workspace / "ch10_live.txt"
    assert target.read_text(encoding="utf-8") == f"{marker}\n"
    assert [mode.value for mode in tui.modes] == [
        "PLAN",
        "DEFAULT",
        "DEFAULT",
        "DEFAULT",
    ]
    assert tui.statuses[-1].last_token_usage is not None
    assert tui.statuses[-1].last_token_usage.total_tokens is not None
    assert not any(
        str(message.get("content", "")).startswith(("/plan", "/do", "/status"))
        for message in context.export_messages()
    )
