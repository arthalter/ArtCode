from pathlib import Path

import pytest

from artcode.sandbox import SeatbeltError, SeatbeltSession


async def test_seatbelt_start_generates_and_reuses_profile(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session = SeatbeltSession(workspace, ())
    try:
        await session.start()
        first = session.profile_path
        assert first is not None and first.is_file()
        assert session.command_prefix()[0] == "/usr/bin/sandbox-exec"
        assert session.profile_path == first
    finally:
        session.close()
    assert not first.exists()


async def test_missing_sandbox_exec_fails_closed(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session = SeatbeltSession(workspace, (), sandbox_exec=tmp_path / "missing")
    with pytest.raises(SeatbeltError, match="找不到"):
        await session.start()


async def test_real_profile_allows_workspace_write_and_denies_external_write(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    session = SeatbeltSession(workspace, ())
    try:
        await session.start()
        allowed = await _run(session, "/bin/zsh", "-f", "-c", f"printf ok > '{workspace / 'ok'}'")
        denied = await _run(session, "/bin/zsh", "-f", "-c", f"printf no > '{outside / 'no'}'")
        assert allowed == 0
        assert denied != 0
        assert (workspace / "ok").read_text() == "ok"
        assert not (outside / "no").exists()
    finally:
        session.close()


async def _run(session: SeatbeltSession, *argv: str) -> int:
    import asyncio

    process = await asyncio.create_subprocess_exec(*session.command_prefix(), *argv)
    return await process.wait()
