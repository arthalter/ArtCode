from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from artcode.tools.process import ProcessResult, ProcessSupervisor

pytestmark = pytest.mark.ch10_5


def python(source: str) -> tuple[str, ...]:
    return (sys.executable, "-c", source)


def environment(**extra: str) -> dict[str, str]:
    selected = dict(os.environ)
    selected.update(extra)
    return selected


@pytest.mark.parametrize(
    ("source", "expected_stdout", "expected_stderr"),
    [
        ("print('hello')", b"hello\n", b""),
        ("import sys;sys.stderr.write('error')", b"", b"error"),
        ("import sys;print('out');sys.stderr.write('err')", b"out\n", b"err"),
        ("import os;print(os.getcwd())", None, b""),
        ("import os;print(os.environ['ARTCODE_TEST_VALUE'])", b"visible\n", b""),
        ("print('你好')", "你好\n".encode(), b""),
    ],
    ids=("stdout", "stderr", "both", "cwd", "environment", "unicode"),
)
async def test_success_collects_complete_process_output(
    tmp_path,
    source,
    expected_stdout,
    expected_stderr,
) -> None:
    result = await ProcessSupervisor().run(
        python(source),
        tmp_path,
        environment(ARTCODE_TEST_VALUE="visible"),
        2,
    )

    assert result.returncode == 0
    assert result.start_error is None
    assert not result.timed_out
    if expected_stdout is None:
        assert result.stdout.decode().strip() == str(tmp_path)
    else:
        assert result.stdout == expected_stdout
    assert result.stderr == expected_stderr


@pytest.mark.parametrize("code", [0, 1, 2, 17, 255], ids=("zero", "one", "two", "seventeen", "max-byte"))
async def test_exit_code_is_preserved(tmp_path, code) -> None:
    result = await ProcessSupervisor().run(
        python(f"raise SystemExit({code})"),
        tmp_path,
        environment(),
        2,
    )

    assert result.returncode == code
    assert not result.timed_out


@pytest.mark.parametrize(
    "scenario",
    ["empty", "missing-executable", "missing-cwd", "permission", "invalid-env"],
    ids=("empty", "missing-executable", "missing-cwd", "permission", "invalid-env"),
)
async def test_start_failure_is_returned_without_child(tmp_path, scenario) -> None:
    argv = python("pass")
    cwd = tmp_path
    env = environment()
    if scenario == "empty":
        argv = ()
    elif scenario == "missing-executable":
        argv = (str(tmp_path / "missing"),)
    elif scenario == "missing-cwd":
        cwd = tmp_path / "missing"
    elif scenario == "permission":
        executable = tmp_path / "not-executable"
        executable.write_text("#!/bin/sh\n", encoding="utf-8")
        executable.chmod(0o600)
        argv = (str(executable),)
    else:
        env = {"INVALID": 1}

    result = await ProcessSupervisor().run(argv, cwd, env, 2)

    assert result.returncode is None
    assert result.start_error


@pytest.mark.parametrize(
    "source",
    [
        "import time;time.sleep(60)",
        "import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(60)",
        "import sys,time;print('before',flush=True);time.sleep(60)",
        "import sys,time;sys.stderr.write('before');sys.stderr.flush();time.sleep(60)",
        "import subprocess,sys,time;subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']);time.sleep(60)",
        "import time;time.sleep(.2)",
    ],
    ids=("sleep", "ignore-term", "stdout", "stderr", "child", "short-race"),
)
async def test_timeout_returns_reaped_result(tmp_path, source) -> None:
    result = await ProcessSupervisor().run(
        python(source),
        tmp_path,
        environment(),
        0.03,
    )

    assert result.timed_out
    assert result.returncode is not None
    assert result.start_error is None


@pytest.mark.parametrize(
    "source",
    [
        "import time;time.sleep(60)",
        "import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(60)",
        "import sys,time;print('before',flush=True);time.sleep(60)",
        "import sys,time;sys.stderr.write('before');sys.stderr.flush();time.sleep(60)",
        "import subprocess,sys,time;subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']);time.sleep(60)",
        "import time;time.sleep(.2)",
    ],
    ids=("sleep", "ignore-term", "stdout", "stderr", "child", "short-race"),
)
async def test_cancellation_is_re_raised_after_cleanup(tmp_path, source) -> None:
    task = asyncio.create_task(
        ProcessSupervisor().run(python(source), tmp_path, environment(), 10)
    )
    await asyncio.sleep(0.03)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.parametrize(
    ("source", "stdout_size", "stderr_size"),
    [
        ("import sys;sys.stdout.write('x'*1000)", 1000, 0),
        ("import sys;sys.stdout.write('x'*131072)", 131072, 0),
        ("import sys;sys.stderr.write('y'*131072)", 0, 131072),
        ("import os;os.write(1,b'\\xff'*4096);os.write(2,b'\\xfe'*4096)", 4096, 4096),
    ],
    ids=("small", "large-stdout", "large-stderr", "binary-both"),
)
async def test_pipe_collection_does_not_truncate_or_deadlock(tmp_path, source, stdout_size, stderr_size) -> None:
    result = await ProcessSupervisor().run(
        python(source),
        tmp_path,
        environment(),
        2,
    )

    assert len(result.stdout) == stdout_size
    assert len(result.stderr) == stderr_size
    assert result.returncode == 0


@pytest.mark.parametrize("field", ["argv", "timed_out", "start_error"], ids=("argv", "timeout", "error"))
def test_process_result_is_immutable_and_explicit(field) -> None:
    result = ProcessResult(("tool",), 0)

    with pytest.raises(FrozenInstanceError):
        setattr(result, field, None)
