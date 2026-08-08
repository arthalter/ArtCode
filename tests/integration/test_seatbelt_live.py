from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from artcode.sandbox import SeatbeltSession


async def test_real_seatbelt_file_sensitive_network_and_child_boundaries(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    sensitive = tmp_path / "secret.txt"
    workspace.mkdir()
    outside.mkdir()
    sensitive.write_text("TOP_SECRET", encoding="utf-8")
    session = SeatbeltSession(workspace, (sensitive,))
    try:
        await session.start()
        assert await run(session, "/bin/zsh", "-f", "-c", f"printf ok > '{workspace / 'ok.txt'}'") == 0
        assert await run(session, "/bin/zsh", "-f", "-c", f"cat '{sensitive}'") != 0
        assert await run(session, "/bin/zsh", "-f", "-c", f"printf no > '{outside / 'no.txt'}'") != 0
        assert (
            await run(
                session,
                sys.executable,
                "-c",
                f"from pathlib import Path; Path({str(outside / 'child.txt')!r}).write_text('no')",
            )
            != 0
        )
        server = await asyncio.start_server(lambda _r, w: w.close(), "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            assert (
                await run(
                    session,
                    sys.executable,
                    "-c",
                    f"import socket; socket.create_connection(('127.0.0.1',{port}),1)",
                )
                != 0
            )
            for host, target_port in (("192.168.0.1", 80), ("1.1.1.1", 53)):
                assert (
                    await run(
                        session,
                        sys.executable,
                        "-c",
                        "import socket; "
                        f"s=socket.socket(); s.settimeout(1); s.connect(({host!r},{target_port}))",
                    )
                    != 0
                )
        finally:
            server.close()
            await server.wait_closed()
        assert (workspace / "ok.txt").read_text(encoding="utf-8") == "ok"
        assert not (outside / "no.txt").exists()
        assert not (outside / "child.txt").exists()
    finally:
        session.close()


async def run(session: SeatbeltSession, *argv: str) -> int:
    process = await asyncio.create_subprocess_exec(
        *session.command_prefix(),
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await process.communicate()
    return int(process.returncode or 0)
