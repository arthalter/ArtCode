from __future__ import annotations

from io import StringIO

from rich.console import Console

from artcode.tools import ToolPreview
from artcode.tools.results import success_result
from artcode.tui.render import TuiRenderer
from artcode.commands import DisplayMode
from artcode.runtime.state import RuntimeStatusSnapshot, StartupStatusSnapshot
from artcode.agent import TokenUsage
from artcode.mcp.models import (
    FailureStage,
    McpServerReport,
    McpStartupReport,
    ServerSource,
    ServerState,
)
import pytest


def capture_renderer() -> tuple[TuiRenderer, Console]:
    console = Console(record=True, width=120)
    return TuiRenderer(console=console), console


def test_startup_status_contains_non_sensitive_fields() -> None:
    renderer, console = capture_renderer()
    status = StartupStatusSnapshot(
        protocol="openai",
        model="deepseek-v4-flash",
        base_url="https://api.deepseek.com",
        streaming=True,
        thinking_enabled=True,
        api_key_configured=True,
        workspace="/tmp/artcode-sandbox",
    )

    renderer.show_startup(status)
    output = console.export_text()

    assert "ArtCode" in output
    assert "protocol: openai" in output
    assert "model: deepseek-v4-flash" in output
    assert "base_url: https://api.deepseek.com" in output
    assert "streaming: on" in output
    assert "thinking: on (high)" in output
    assert "/tmp/artcode-sandbox" in output
    assert "context: 1000000 tokens" in output
    assert "api_key: configured" in output
    assert "sk-test-secret-value" not in output


def test_help_displays_commands() -> None:
    renderer, console = capture_renderer()

    renderer.show_help("/exit\n/quit\n/help\n/plan 任务描述\n/do [附加说明]")

    output = console.export_text()
    assert "/plan 任务描述" in output
    assert "/do [附加说明]" in output


def test_stream_delta_outputs_raw_text() -> None:
    renderer, console = capture_renderer()

    renderer.stream_delta("`code`\n    indented")

    output = console.export_text()
    assert "`code`" in output
    assert "    indented" in output


def test_tool_preview_is_rendered() -> None:
    renderer, console = capture_renderer()
    preview = ToolPreview("write_file", "写入文件 /tmp/a.txt", "/tmp/a.txt", True)

    renderer.show_tool_preview(preview)

    output = console.export_text()
    assert "write_file" in output
    assert "/tmp/a.txt" in output


def test_tool_result_summary_does_not_print_full_content() -> None:
    renderer, console = capture_renderer()
    result = success_result("read_file", "读取成功。", "SECRET_FULL_CONTENT")

    renderer.show_tool_result_summary(result)

    output = console.export_text()
    assert "读取成功" in output
    assert "SECRET_FULL_CONTENT" not in output


def test_agent_progress_rendering() -> None:
    renderer, console = capture_renderer()

    renderer.show_agent_iteration(2, 12)
    renderer.show_tool_calls_received(3)
    renderer.show_tool_batch_started(1, "read_only", 2)
    renderer.show_token_usage(10, 20, 30)
    renderer.show_agent_stopped("iteration_limit", "达到上限")

    output = console.export_text()
    assert "第 2/12 轮" in output
    assert "3 个工具调用" in output
    assert "read_only" in output
    assert "total=30" in output
    assert "iteration_limit" in output


def test_token_usage_rendering_includes_cache_fields() -> None:
    renderer, console = capture_renderer()

    renderer.show_token_usage(10, 20, 30, cached_tokens=7, cache_miss_tokens=3)

    output = console.export_text()
    assert "cached=7" in output
    assert "miss=3" in output


def test_context_status_is_compact_and_does_not_print_history() -> None:
    renderer, console = capture_renderer()

    renderer.show_context_status(
        {
            "trigger": "automatic",
            "status": "success",
            "before_tokens": 167_420,
            "after_tokens": 18_430,
            "persisted_count": 2,
            "circuit_open": False,
        }
    )

    output = console.export_text()
    assert "automatic / success" in output
    assert "167420 → 18430" in output
    assert "存盘 2 个" in output
    assert "熔断 closed" in output


def test_prompt_and_labels_include_display_mode() -> None:
    renderer, console = capture_renderer()

    assert renderer.prompt_text("deepseek", DisplayMode.DEFAULT) == "[DEFAULT] deepseek > "
    assert renderer.prompt_text("deepseek", DisplayMode.PLAN) == "[PLAN] deepseek > "
    renderer.show_user_label(DisplayMode.DEFAULT)
    renderer.show_assistant_label(DisplayMode.PLAN)

    output = console.export_text()
    assert "[DEFAULT] User" in output
    assert "[PLAN] ArtCode" in output


def test_clear_screen_emits_terminal_clear_and_home_controls() -> None:
    stream = StringIO()
    console = Console(
        file=stream,
        force_terminal=True,
        _environ={"TERM": "xterm-256color"},
    )

    TuiRenderer(console).clear_screen()

    assert stream.getvalue() == "\x1b[2J\x1b[H"


def test_runtime_status_renders_whitelist_and_missing_values_without_secrets() -> None:
    renderer, console = capture_renderer()
    snapshot = RuntimeStatusSnapshot(
        model="deepseek-v4-flash",
        workspace="/tmp/workspace",
        display_mode=DisplayMode.DEFAULT,
        permission_mode="full",
        shell_policy="auto",
        seatbelt_status="self-test passed",
        session_id=None,
        session_state="不可用",
        estimated_context_tokens=None,
        context_window_tokens=200_000,
        last_token_usage=TokenUsage(
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
            cached_tokens=None,
            cache_miss_tokens=3,
        ),
    )

    renderer.show_runtime_status(snapshot)

    output = console.export_text()
    assert "运行状态" in output
    assert "deepseek-v4-flash" in output
    assert "/tmp/workspace" in output
    assert "显示模式：DEFAULT" in output
    assert "当前上下文估算：不可用" in output
    assert "total=15" in output
    assert "cached=不可用" in output
    assert "sk-test-secret" not in output
    assert "MEMORY_SECRET_BODY" not in output


@pytest.mark.ch10_5
@pytest.mark.parametrize("issue_count", [0, 1, 2, 4, 8])
def test_mcp_startup_renderer_exposes_counts_without_secret_values(issue_count: int) -> None:
    renderer, console = capture_renderer()
    issues = tuple(f"mcp__server__tool_{index}：冲突" for index in range(issue_count))
    report = McpStartupReport(
        configured_count=1,
        server_reports=(
            McpServerReport(
                "server",
                ServerSource.USER,
                ServerState.READY,
                tool_count=3 - min(issue_count, 3),
                failure_stage=FailureStage.REGISTRATION if issues else None,
                detail="；".join(issues),
                registration_issues=issues,
            ),
        ),
        registered_tool_count=3 - min(issue_count, 3),
    )

    renderer.show_mcp_startup(report)

    output = console.export_text()
    assert f"注册问题 {issue_count}" in output
    assert "server [user] ready" in output
    assert "Bearer renderer-secret" not in output
