from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from artcode.permissions import ShellPolicy
from artcode.sandbox import SeatbeltSession
from artcode.tools import PreparedToolCall, ToolExecutionContext, WorkspacePathPolicy
from artcode.tools.command_tool import RunCommandTool
from artcode.workspace import Workspace


def command_context(workspace: Path, session: SeatbeltSession) -> ToolExecutionContext:
    return ToolExecutionContext(
        WorkspacePathPolicy(Workspace.from_path(workspace)),
        default_cwd=workspace,
        shell_policy=ShellPolicy.SANDBOX_AUTO,
        seatbelt=session,
    )


async def execute_probe(
    context: ToolExecutionContext,
    filename: str,
    content: str = "executed",
):
    tool = RunCommandTool()
    prepared = tool.prepare(
        {"command": f"printf {content} > {filename}"},
        context,
    )
    assert isinstance(prepared, PreparedToolCall)
    return await tool.execute(prepared, context)


async def test_deleted_profile_fails_closed_and_can_be_reinitialized(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session = SeatbeltSession(workspace, ())
    try:
        await session.start()
        context = command_context(workspace, session)
        profile = session.profile_path
        assert profile is not None
        profile.unlink()

        failed = await execute_probe(context, "must-not-exist.txt")

        assert failed.ok is False
        assert failed.error_code == "sandbox_error"
        assert not (workspace / "must-not-exist.txt").exists()

        await session.start()
        recovered = await execute_probe(context, "recovered.txt", "recovered")

        assert recovered.ok is True
        assert (workspace / "recovered.txt").read_text(encoding="utf-8") == "recovered"
    finally:
        session.close()


async def test_corrupt_profile_uses_sandbox_exec_once_and_never_falls_back(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session = SeatbeltSession(workspace, ())
    try:
        await session.start()
        context = command_context(workspace, session)
        profile = session.profile_path
        assert profile is not None
        profile.write_text("(version 1)\n(this-is-invalid)\n", encoding="utf-8")

        real_create_subprocess_exec = asyncio.create_subprocess_exec
        launches: list[tuple[Any, ...]] = []

        async def recording_create_subprocess_exec(*args: Any, **kwargs: Any):
            launches.append(args)
            return await real_create_subprocess_exec(*args, **kwargs)

        monkeypatch.setattr(asyncio, "create_subprocess_exec", recording_create_subprocess_exec)

        result = await execute_probe(context, "must-not-exist.txt")

        assert result.ok is False
        assert result.error_code == "command_failed"
        assert not (workspace / "must-not-exist.txt").exists()
        assert len(launches) == 1
        assert launches[0][:3] == (
            "/usr/bin/sandbox-exec",
            "-f",
            str(profile),
        )
        assert launches[0][3:7] == (
            "/bin/zsh",
            "-f",
            "-c",
            "printf executed > must-not-exist.txt",
        )
        assert not any(args and args[0] == "/bin/zsh" for args in launches)

        monkeypatch.setattr(asyncio, "create_subprocess_exec", real_create_subprocess_exec)
        await session.start()
        recovered = await execute_probe(context, "recovered.txt", "recovered")

        assert recovered.ok is True
        assert (workspace / "recovered.txt").read_text(encoding="utf-8") == "recovered"
    finally:
        session.close()
