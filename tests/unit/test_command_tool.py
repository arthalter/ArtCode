from __future__ import annotations

from artcode.tools.base import PreparedToolCall, ToolExecutionContext
from artcode.tools.command_tool import RunCommandTool
from artcode.tools.policy import AllowedPathPolicy
import asyncio


def context_for(root, timeout: float = 10.0, max_result_bytes: int = 20_000) -> ToolExecutionContext:
    root.mkdir()
    return ToolExecutionContext(
        AllowedPathPolicy((root,)),
        command_timeout_seconds=timeout,
        max_result_bytes=max_result_bytes,
        default_cwd=root,
    )


async def run_prepared(arguments, context: ToolExecutionContext):
    tool = RunCommandTool()
    prepared = tool.prepare(arguments, context)
    assert isinstance(prepared, PreparedToolCall)
    return await tool.execute(prepared, context)


def test_run_command_preview_contains_command(tmp_path) -> None:
    context = context_for(tmp_path / "sandbox")

    prepared = RunCommandTool().prepare({"command": "pwd"}, context)

    assert isinstance(prepared, PreparedToolCall)
    assert "pwd" in prepared.preview.summary
    assert prepared.preview.requires_confirmation is True


async def test_run_command_executes_inside_allowed_dir(tmp_path) -> None:
    context = context_for(tmp_path / "sandbox")

    result = await run_prepared({"command": "printf hello"}, context)

    assert result.ok is True
    assert "hello" in result.content
    assert "exit_code: 0" in result.content


async def test_run_command_reports_nonzero_exit(tmp_path) -> None:
    context = context_for(tmp_path / "sandbox")

    result = await run_prepared({"command": "printf err >&2; exit 3"}, context)

    assert result.ok is False
    assert result.error_code == "command_failed"
    assert "exit_code: 3" in result.content
    assert "err" in result.content


def test_run_command_rejects_outside_cwd(tmp_path) -> None:
    context = context_for(tmp_path / "sandbox")

    result = RunCommandTool().prepare({"command": "pwd", "cwd": str(tmp_path)}, context)

    assert result.ok is False
    assert result.error_code == "path_outside_allowed_dirs"


def test_run_command_rejects_dangerous_command(tmp_path) -> None:
    context = context_for(tmp_path / "sandbox")

    result = RunCommandTool().prepare({"command": "sudo echo nope"}, context)

    assert result.ok is False
    assert result.error_code == "dangerous_command"


def test_rejected_dangerous_command_is_not_executed(tmp_path) -> None:
    context = context_for(tmp_path / "sandbox")
    target = context.default_cwd / "created.txt"

    result = RunCommandTool().prepare({"command": f"sudo touch {target}"}, context)

    assert result.ok is False
    assert not target.exists()


async def test_run_command_times_out(tmp_path) -> None:
    context = context_for(tmp_path / "sandbox", timeout=0.05)

    result = await run_prepared({"command": "sleep 1"}, context)

    assert result.ok is False
    assert result.error_code == "command_timeout"


async def test_run_command_truncates_large_output(tmp_path) -> None:
    context = context_for(tmp_path / "sandbox", max_result_bytes=30)

    result = await run_prepared({"command": "printf 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'"}, context)

    assert result.truncated is True
    assert len(result.content.encode("utf-8")) <= 30


async def test_shell_environment_does_not_inherit_secrets(tmp_path, monkeypatch) -> None:
    context = context_for(tmp_path / "sandbox")
    monkeypatch.setenv("DEEPEST_SECRET_TOKEN", "never-expose-this")

    result = await run_prepared({"command": "env"}, context)

    assert result.ok is True
    assert "DEEPEST_SECRET_TOKEN" not in result.content
    assert "never-expose-this" not in result.content


async def test_timeout_kills_entire_process_group(tmp_path) -> None:
    context = context_for(tmp_path / "sandbox", timeout=0.1)
    marker = context.default_cwd / "child.log"
    command = f"while true; do printf x >> '{marker}'; sleep 0.01; done & wait"

    result = await run_prepared({"command": command}, context)
    size_after_timeout = marker.stat().st_size
    await asyncio.sleep(0.08)

    assert result.error_code == "command_timeout"
    assert marker.stat().st_size == size_after_timeout
