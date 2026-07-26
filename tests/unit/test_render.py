from __future__ import annotations

from rich.console import Console

from artcode.config import SafeConfigStatus
from artcode.tools import ToolPreview
from artcode.tools.results import success_result
from artcode.tui.render import TuiRenderer


def capture_renderer() -> tuple[TuiRenderer, Console]:
    console = Console(record=True, width=120)
    return TuiRenderer(console=console), console


def test_startup_status_contains_non_sensitive_fields() -> None:
    renderer, console = capture_renderer()
    status = SafeConfigStatus(
        chapter="ch05：System Prompt 设计",
        protocol="openai",
        model="deepseek-v4-flash",
        base_url="https://api.deepseek.com",
        streaming=True,
        thinking_enabled=True,
        thinking_effort="high",
        masked_api_key="sk-t...alue",
        workspace="/tmp/artcode-sandbox",
    )

    renderer.show_startup(status)
    output = console.export_text()

    assert "ArtCode" in output
    assert "ch05：System Prompt 设计" in output
    assert "protocol: openai" in output
    assert "model: deepseek-v4-flash" in output
    assert "base_url: https://api.deepseek.com" in output
    assert "streaming: on" in output
    assert "thinking: on (high)" in output
    assert "/tmp/artcode-sandbox" in output
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
