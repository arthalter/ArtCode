from __future__ import annotations

import asyncio

import pytest

from artcode.agent import NORMAL_AGENT_MODE
from artcode.permissions import PermissionState, ShellPolicy
from artcode.tools import PreparedToolCall, ToolEnvironment, ToolRunContext
from artcode.tools.command_tool import RunCommandTool
from artcode.tools.process import ProcessResult

pytestmark = pytest.mark.ch10_5


def context_for(root, *, timeout=2):
    environment = ToolEnvironment.from_workspace(
        root,
        command_timeout_seconds=timeout,
    )
    return ToolRunContext(
        environment,
        NORMAL_AGENT_MODE,
        PermissionState(shell_policy=ShellPolicy.UNSANDBOXED_ASK).snapshot(),
    )


async def run_command(root, command, *, timeout=2, tool=None):
    selected = tool or RunCommandTool()
    context = context_for(root, timeout=timeout)
    prepared = selected.prepare({"command": command}, context)
    assert isinstance(prepared, PreparedToolCall)
    return await selected.execute(prepared, context)


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("printf hello", "hello"),
        ("printf err >&2", "err"),
        ("pwd", None),
        ("printf '你好'", "你好"),
        ("mkdir -p nested && printf value > nested/note.txt && cat nested/note.txt", "value"),
    ],
    ids=("stdout", "stderr", "cwd", "unicode", "filesystem"),
)
async def test_command_tool_runs_real_supervised_process(tmp_path, command, expected) -> None:
    result = await run_command(tmp_path, command)

    assert result.ok
    assert "exit_code: 0" in result.content
    assert (str(tmp_path) if expected is None else expected) in result.content


@pytest.mark.parametrize("code", [1, 7, 127], ids=("one", "seven", "one-twenty-seven"))
async def test_nonzero_process_maps_to_command_failed(tmp_path, code) -> None:
    result = await run_command(tmp_path, f"printf failure >&2; exit {code}")

    assert result.error_code == "command_failed"
    assert f"exit_code: {code}" in result.content
    assert "failure" in result.content


@pytest.mark.parametrize(
    "command",
    [
        "sleep 60",
        "printf before; sleep 60",
        "(while true; do printf x >> child.log; sleep .01; done) & wait",
    ],
    ids=("sleep", "output-before", "child-writer"),
)
async def test_timeout_maps_to_structured_result_and_stops_output(tmp_path, command) -> None:
    result = await run_command(tmp_path, command, timeout=0.08)

    assert result.error_code == "command_timeout"
    marker = tmp_path / "child.log"
    if marker.exists():
        size = marker.stat().st_size
        await asyncio.sleep(0.05)
        assert marker.stat().st_size == size


@pytest.mark.parametrize(
    "command",
    ["sleep 60", "(sleep 60) & wait"],
    ids=("single", "child"),
)
async def test_cancelling_command_tool_propagates_after_process_cleanup(tmp_path, command) -> None:
    task = asyncio.create_task(run_command(tmp_path, command, timeout=10))
    await asyncio.sleep(0.05)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task


async def test_process_start_error_maps_to_command_error(tmp_path) -> None:
    class FailedSupervisor:
        async def run(self, argv, cwd, env, timeout_seconds):
            return ProcessResult(tuple(argv), None, start_error="injected launch failure")

    result = await run_command(tmp_path, "printf never", tool=RunCommandTool(FailedSupervisor()))

    assert result.error_code == "command_error"
    assert "injected launch failure" in result.message


async def test_command_environment_drops_unapproved_secret(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ARTCODE_PROCESS_SECRET", "must-not-leak")

    result = await run_command(tmp_path, "env")

    assert result.ok
    assert "ARTCODE_PROCESS_SECRET" not in result.content
    assert "must-not-leak" not in result.content
