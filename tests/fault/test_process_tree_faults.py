from __future__ import annotations

import asyncio
import os

import pytest

from artcode.tools.process import ProcessSupervisor
from tests.fixtures.processes import process_tree_command

pytestmark = [pytest.mark.ch10_5, pytest.mark.fault]


SCENARIOS = (
    (False, 0, 0),
    (True, 0, 0),
    (False, 4096, 0),
    (False, 0, 4096),
    (True, 65536, 65536),
)


async def wait_for_pids(path, timeout=3) -> list[int]:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if path.exists():
            values = [int(value) for value in path.read_text().splitlines()]
            if len(values) == 3:
                return values
        await asyncio.sleep(0.01)
    raise AssertionError("process tree did not publish three PIDs")


def pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


async def assert_pids_gone(pids: list[int], timeout=3) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if not any(pid_exists(pid) for pid in pids):
            return
        await asyncio.sleep(0.01)
    assert not [pid for pid in pids if pid_exists(pid)]


@pytest.mark.parametrize(
    ("ignore_term", "stdout_size", "stderr_size"),
    SCENARIOS,
    ids=("normal", "ignore-term", "stdout", "stderr", "high-output"),
)
async def test_timeout_sigkills_and_reaps_parent_child_grandchild(
    tmp_path,
    ignore_term,
    stdout_size,
    stderr_size,
) -> None:
    pid_file = tmp_path / "pids.txt"
    task = asyncio.create_task(
        ProcessSupervisor().run(
            process_tree_command(
                str(pid_file),
                ignore_term=ignore_term,
                stdout_size=stdout_size,
                stderr_size=stderr_size,
            ),
            tmp_path,
            dict(os.environ),
            0.2,
        )
    )
    pids = await wait_for_pids(pid_file)

    result = await task

    assert result.timed_out
    await assert_pids_gone(pids)


@pytest.mark.parametrize(
    ("ignore_term", "stdout_size", "stderr_size"),
    SCENARIOS,
    ids=("normal", "ignore-term", "stdout", "stderr", "high-output"),
)
async def test_cancellation_sigkills_and_reaps_parent_child_grandchild(
    tmp_path,
    ignore_term,
    stdout_size,
    stderr_size,
) -> None:
    pid_file = tmp_path / "pids.txt"
    task = asyncio.create_task(
        ProcessSupervisor().run(
            process_tree_command(
                str(pid_file),
                ignore_term=ignore_term,
                stdout_size=stdout_size,
                stderr_size=stderr_size,
            ),
            tmp_path,
            dict(os.environ),
            10,
        )
    )
    pids = await wait_for_pids(pid_file)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    await assert_pids_gone(pids)
