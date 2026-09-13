from __future__ import annotations

import json
from pathlib import Path
import re
import shlex
import sys

import pytest

from artcode._tool import LocalTools
from artcode._workspace import LocalWorkspace
from artcode.core.tool import ApprovalChoice, PermissionMode, RunMode, ShellPolicy, ToolCall


class AllowCommand:
    async def approve(self, request):
        return ApprovalChoice.ALLOW_ONCE


def call(name: str, **arguments: object) -> ToolCall:
    return ToolCall(name, name, json.dumps(arguments))


@pytest.mark.parametrize("stream,exit_code", [("stdout", 0), ("stderr", 1)])
async def test_truncated_command_output_can_be_read_to_its_final_line(
    tmp_path: Path, stream: str, exit_code: int
) -> None:
    workspace = LocalWorkspace(tmp_path)
    tools = LocalTools(permission_mode=PermissionMode.FULL, shell_policy=ShellPolicy.EXPLICIT_UNSAFE)
    script = (
        "import sys; "
        f"sys.{stream}.write(('ordinary build log line ' * 3 + '\\n') * 1000 + 'IMPORTANT_END\\n'); "
        f"sys.exit({exit_code})"
    )
    command = shlex.join((sys.executable, "-c", script))
    try:
        run = tools.open_run(workspace, RunMode.ACT)
        result, = await tools.execute_batch(
            run, (call("run_command", command=command),), approver=AllowCommand()
        )
        assert result.ok is (exit_code == 0)
        assert result.error_code == (None if exit_code == 0 else "command_failed")
        assert "已截断" in result.content
        reference = re.search(r"result:[0-9a-f]{32}:[0-9a-f]{32}", result.content)
        assert reference is not None
        assert "read_file" in result.content
        tail, = await tools.execute_batch(
            run, (call("read_file", path=reference.group(), start_line=1001, end_line=1001),)
        )
        assert tail.ok is True
        assert tail.content == "IMPORTANT_END\n"
    finally:
        await tools.close()
        await workspace.aclose()


async def test_result_read_requires_a_range_and_rejects_another_workspace_scope(tmp_path: Path) -> None:
    workspace = LocalWorkspace(tmp_path)
    tools = LocalTools()
    other_root = tmp_path / "other"
    other_root.mkdir()
    other = LocalWorkspace(other_root)
    reference = other.store_result("foreign", "private result\n").reference
    own_reference = workspace.store_result("own", "own result\n").reference
    try:
        run = tools.open_run(workspace, RunMode.CHAT)
        missing_range, foreign = await tools.execute_batch(
            run,
            (
                call("read_file", path=own_reference),
                call("read_file", path=reference, start_line=1, end_line=1),
            ),
        )
        assert missing_range.ok is False and "行范围" in missing_range.content
        assert foreign.ok is False and "scope" in foreign.content
        assert "private result" not in foreign.content
    finally:
        await tools.close()
        await workspace.aclose()
        await other.aclose()


async def test_small_command_output_keeps_its_existing_format(tmp_path: Path) -> None:
    workspace = LocalWorkspace(tmp_path)
    tools = LocalTools(shell_policy=ShellPolicy.EXPLICIT_UNSAFE)
    try:
        result, = await tools.execute_batch(
            tools.open_run(workspace, RunMode.ACT),
            (call("run_command", command="printf ok"),),
            approver=AllowCommand(),
        )
        assert result.ok is True
        assert result.content == "exit_code: 0\nstdout:\nok\nstderr:\n"
    finally:
        await tools.close()
        await workspace.aclose()


@pytest.mark.parametrize("path", ["result:notes.txt", "result:logs/build.txt"])
async def test_result_prefix_in_regular_paths_is_still_a_file(tmp_path: Path, path: str) -> None:
    target = tmp_path / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("ordinary file\n", encoding="utf-8")
    workspace = LocalWorkspace(tmp_path)
    tools = LocalTools()
    try:
        result, = await tools.execute_batch(
            tools.open_run(workspace, RunMode.CHAT), (call("read_file", path=path),)
        )
        assert result.ok is True
        assert result.content == "ordinary file\n"
    finally:
        await tools.close()
        await workspace.aclose()
