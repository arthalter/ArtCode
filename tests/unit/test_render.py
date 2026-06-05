from __future__ import annotations

from rich.console import Console

from artcode.config import SafeConfigStatus
from artcode.tui.render import TuiRenderer


def capture_renderer() -> tuple[TuiRenderer, Console]:
    console = Console(record=True, width=120)
    return TuiRenderer(console=console), console


def test_startup_status_contains_non_sensitive_fields() -> None:
    renderer, console = capture_renderer()
    status = SafeConfigStatus(
        chapter="ch02：让AI说话",
        protocol="openai",
        model="deepseek-v4-flash",
        base_url="https://api.deepseek.com",
        streaming=True,
        thinking_enabled=True,
        thinking_effort="high",
        masked_api_key="sk-t...alue",
    )

    renderer.show_startup(status)
    output = console.export_text()

    assert "ArtCode" in output
    assert "ch02：让AI说话" in output
    assert "protocol: openai" in output
    assert "model: deepseek-v4-flash" in output
    assert "base_url: https://api.deepseek.com" in output
    assert "streaming: on" in output
    assert "thinking: on (high)" in output
    assert "sk-test-secret-value" not in output


def test_help_only_displays_three_commands() -> None:
    renderer, console = capture_renderer()

    renderer.show_help("/exit\n/quit\n/help")

    assert console.export_text().strip().splitlines() == ["/exit", "/quit", "/help"]


def test_stream_delta_outputs_raw_text() -> None:
    renderer, console = capture_renderer()

    renderer.stream_delta("`code`\n    indented")

    output = console.export_text()
    assert "`code`" in output
    assert "    indented" in output
