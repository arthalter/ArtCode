from __future__ import annotations

import asyncio
import sys

import pytest

from artcode.sandbox import SeatbeltSession

pytestmark = [pytest.mark.ch10_5, pytest.mark.live]


async def run(session: SeatbeltSession, source: str) -> int:
    process = await asyncio.create_subprocess_exec(
        *session.command_prefix(),
        sys.executable,
        "-c",
        source,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    await process.communicate()
    return int(process.returncode or 0)


async def started_session(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return workspace, await SeatbeltSession(workspace, ()).start()


async def test_live_seatbelt_denies_public_network(tmp_path) -> None:
    _workspace, session = await started_session(tmp_path)
    try:
        code = await run(
            session,
            "import socket;s=socket.socket();s.settimeout(.5);s.connect(('1.1.1.1',80))",
        )
        assert code != 0
    finally:
        session.close()


async def test_live_seatbelt_denies_dns_resolution(tmp_path) -> None:
    _workspace, session = await started_session(tmp_path)
    try:
        assert await run(session, "import socket;socket.getaddrinfo('example.com',80)") != 0
    finally:
        session.close()


async def test_live_seatbelt_denies_loopback_connection(tmp_path) -> None:
    _workspace, session = await started_session(tmp_path)
    server = await asyncio.start_server(lambda _reader, writer: writer.close(), "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        code = await run(
            session,
            f"import socket;s=socket.socket();s.settimeout(.5);s.connect(('127.0.0.1',{port}))",
        )
        assert code != 0
    finally:
        server.close()
        await server.wait_closed()
        session.close()


async def test_live_seatbelt_denies_local_listener(tmp_path) -> None:
    _workspace, session = await started_session(tmp_path)
    try:
        assert await run(
            session,
            "import socket;s=socket.socket();s.bind(('127.0.0.1',0));s.listen()",
        ) != 0
    finally:
        session.close()


async def test_live_seatbelt_network_denial_is_inherited_by_child(tmp_path) -> None:
    workspace, session = await started_session(tmp_path)
    marker = workspace / "network-succeeded"
    child = (
        "import pathlib,socket;"
        "s=socket.socket();s.settimeout(.5);s.connect(('1.1.1.1',80));"
        f"pathlib.Path({str(marker)!r}).write_text('bad')"
    )
    parent = f"import subprocess,sys;raise SystemExit(subprocess.run([sys.executable,'-c',{child!r}]).returncode)"
    try:
        assert await run(session, parent) != 0
        assert not marker.exists()
    finally:
        session.close()
