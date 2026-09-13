from __future__ import annotations

import asyncio
import os
from pathlib import Path
import sys

import pytest

from artcode._workspace import LocalWorkspace
from artcode.core.workspace import IsolationMode, ProcessRequest


async def test_timeout_kills_descendant_process_tree(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    sentinel = root / "descendant-survived"
    script = (
        "import subprocess,sys,time; "
        "subprocess.Popen([sys.executable,'-c',"
        f"\"import time,pathlib; time.sleep(0.4); pathlib.Path({str(sentinel)!r}).write_text('bad')\"]); "
        "time.sleep(30)"
    )
    scope = LocalWorkspace(root)

    outcome = await scope.run_process(
        ProcessRequest(
            argv=(sys.executable, "-c", script),
            timeout_seconds=0.1,
            isolation=IsolationMode.EXPLICIT_UNSAFE,
        )
    )
    await asyncio.sleep(0.6)

    assert outcome.timed_out is True
    assert not sentinel.exists()


async def test_cancellation_kills_process_tree_and_reraises(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    scope = LocalWorkspace(root)
    task = asyncio.create_task(
        scope.run_process(
            ProcessRequest(
                argv=(sys.executable, "-c", "import time; time.sleep(30)"),
                isolation=IsolationMode.EXPLICIT_UNSAFE,
            )
        )
    )
    for _ in range(100):
        if scope.active_process_count:
            break
        await asyncio.sleep(0.01)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert scope.active_process_count == 0
