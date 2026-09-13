from __future__ import annotations

import asyncio
from pathlib import Path
import sys

import pytest

from artcode._workspace import LocalWorkspace
from artcode.core.workspace import IsolationMode, PathOutsideWorkspace, ProcessRequest, SeatbeltUnavailable


async def test_process_uses_argv_and_explicit_scope_cwd(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    nested = root / "nested"
    nested.mkdir(parents=True)
    scope = LocalWorkspace(root)

    outcome = await scope.run_process(
        ProcessRequest(
            argv=(sys.executable, "-c", "import os; print(os.getcwd())"),
            cwd="nested",
            isolation=IsolationMode.EXPLICIT_UNSAFE,
        )
    )

    assert outcome.returncode == 0
    assert outcome.stdout.strip() == str(nested)
    assert outcome.timed_out is False


async def test_process_rejects_cwd_escape_before_spawn(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    scope = LocalWorkspace(root)

    with pytest.raises(PathOutsideWorkspace):
        await scope.run_process(
            ProcessRequest(
                argv=(sys.executable, "-c", "raise SystemExit(99)"),
                cwd="..",
                isolation=IsolationMode.EXPLICIT_UNSAFE,
            )
        )


async def test_enforced_isolation_fails_closed_when_seatbelt_is_missing(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    scope = LocalWorkspace(root, sandbox_exec=tmp_path / "missing-sandbox-exec")

    with pytest.raises(SeatbeltUnavailable):
        await scope.run_process(
            ProcessRequest(argv=(sys.executable, "-c", "print('must not run')"))
        )


async def test_enforced_isolation_fails_closed_when_seatbelt_self_test_fails(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    failing = tmp_path / "sandbox-exec"
    failing.write_text("#!/bin/sh\nexit 9\n", encoding="utf-8")
    failing.chmod(0o700)
    scope = LocalWorkspace(root, sandbox_exec=failing)

    with pytest.raises(SeatbeltUnavailable, match="自检失败"):
        await scope.run_process(
            ProcessRequest(argv=(sys.executable, "-c", "print('must not run')"))
        )


async def test_large_process_output_is_bounded_and_locatable(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    scope = LocalWorkspace(root, process_output_limit=32)

    outcome = await scope.run_process(
        ProcessRequest(
            argv=(sys.executable, "-c", "print('x' * 200, end='')"),
            isolation=IsolationMode.EXPLICIT_UNSAFE,
        )
    )

    assert len(outcome.stdout) == 32
    assert outcome.stdout_truncated is True
    assert outcome.stdout_reference is not None
    restored = scope.read_result(outcome.stdout_reference, start_line=1, end_line=1)
    assert restored.truncated is False
    assert restored.text == "x" * 200


async def test_process_timeout_is_a_distinct_outcome(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    scope = LocalWorkspace(root)

    outcome = await scope.run_process(
        ProcessRequest(
            argv=(sys.executable, "-c", "import time; time.sleep(30)"),
            timeout_seconds=0.05,
            isolation=IsolationMode.EXPLICIT_UNSAFE,
        )
    )

    assert outcome.timed_out is True
    assert outcome.returncode is not None
    assert scope.active_process_count == 0


async def test_aclose_terminates_active_processes(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    scope = LocalWorkspace(root)
    started = asyncio.Event()

    async def run() -> object:
        started.set()
        return await scope.run_process(
            ProcessRequest(
                argv=(sys.executable, "-c", "import time; time.sleep(30)"),
                isolation=IsolationMode.EXPLICIT_UNSAFE,
            )
        )

    task = asyncio.create_task(run())
    await started.wait()
    for _ in range(100):
        if scope.active_process_count:
            break
        await asyncio.sleep(0.01)
    await scope.aclose()

    assert scope.active_process_count == 0
    assert task.done()
    assert task.cancelled() or (await task).cancelled
