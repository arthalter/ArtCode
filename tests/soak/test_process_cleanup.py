from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

from artcode.tools.process import ProcessSupervisor

pytestmark = [pytest.mark.ch10_5, pytest.mark.soak, pytest.mark.slow]


def env() -> dict[str, str]:
    return dict(os.environ)


def python(source: str) -> tuple[str, ...]:
    return sys.executable, "-c", source


def fd_count() -> int:
    directory = Path("/dev/fd")
    return len(list(directory.iterdir())) if directory.is_dir() else 0


def assert_fd_stable(before: int) -> None:
    after = fd_count()
    if before:
        assert after <= before + 4


async def test_repeated_success_processes_release_pipes(tmp_path) -> None:
    before = fd_count()
    supervisor = ProcessSupervisor()
    for _ in range(40):
        result = await supervisor.run(python("print('ok')"), tmp_path, env(), 2)
        assert result.returncode == 0
    assert_fd_stable(before)


async def test_repeated_failed_processes_release_pipes(tmp_path) -> None:
    before = fd_count()
    supervisor = ProcessSupervisor()
    for _ in range(40):
        result = await supervisor.run(python("raise SystemExit(7)"), tmp_path, env(), 2)
        assert result.returncode == 7
    assert_fd_stable(before)


async def test_repeated_timeouts_leave_no_communicate_tasks(tmp_path) -> None:
    before = fd_count()
    supervisor = ProcessSupervisor()
    for _ in range(20):
        result = await supervisor.run(python("import time;time.sleep(60)"), tmp_path, env(), 0.02)
        assert result.timed_out
    await asyncio.sleep(0)
    assert not [task for task in asyncio.all_tasks() if task is not asyncio.current_task() and not task.done()]
    assert_fd_stable(before)


async def test_repeated_cancellations_leave_no_communicate_tasks(tmp_path) -> None:
    before = fd_count()
    supervisor = ProcessSupervisor()
    for _ in range(20):
        task = asyncio.create_task(
            supervisor.run(python("import time;time.sleep(60)"), tmp_path, env(), 2)
        )
        await asyncio.sleep(0.02)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    await asyncio.sleep(0)
    assert not [task for task in asyncio.all_tasks() if task is not asyncio.current_task() and not task.done()]
    assert_fd_stable(before)


async def test_repeated_high_output_is_complete_without_fd_growth(tmp_path) -> None:
    before = fd_count()
    supervisor = ProcessSupervisor()
    for _ in range(15):
        result = await supervisor.run(
            python("import sys;sys.stdout.write('x'*131072);sys.stderr.write('y'*131072)"),
            tmp_path,
            env(),
            2,
        )
        assert len(result.stdout) == 131072
        assert len(result.stderr) == 131072
    assert_fd_stable(before)
