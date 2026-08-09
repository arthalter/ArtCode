from __future__ import annotations

import asyncio
import os
import signal
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProcessResult:
    argv: tuple[str, ...]
    returncode: int | None
    stdout: bytes = b""
    stderr: bytes = b""
    timed_out: bool = False
    start_error: str | None = None


class ProcessSupervisor:
    async def run(
        self,
        argv: Sequence[str],
        cwd: Path,
        env: Mapping[str, str],
        timeout_seconds: float,
    ) -> ProcessResult:
        selected = tuple(str(value) for value in argv)
        if not selected:
            return ProcessResult(selected, None, start_error="进程参数不能为空。")
        try:
            process = await asyncio.create_subprocess_exec(
                *selected,
                cwd=str(cwd),
                env=dict(env),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
        except asyncio.CancelledError:
            raise
        except (OSError, TypeError, ValueError) as exc:
            return ProcessResult(selected, None, start_error=str(exc))

        communicate = asyncio.create_task(process.communicate())
        try:
            stdout, stderr = await asyncio.wait_for(
                asyncio.shield(communicate),
                timeout=timeout_seconds,
            )
        except TimeoutError:
            await self._kill_and_reap(process, communicate)
            stdout, stderr = communicate.result()
            return ProcessResult(
                selected,
                process.returncode,
                stdout,
                stderr,
                timed_out=True,
            )
        except asyncio.CancelledError:
            await self._kill_and_reap(process, communicate)
            raise
        except BaseException:
            await self._kill_and_reap(process, communicate)
            raise
        return ProcessResult(selected, process.returncode, stdout, stderr)

    async def _kill_and_reap(
        self,
        process: asyncio.subprocess.Process,
        communicate: asyncio.Task[tuple[bytes, bytes]],
    ) -> None:
        if process.returncode is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        try:
            await asyncio.shield(communicate)
        except asyncio.CancelledError:
            # A second cancellation must not abandon the child process. Finish
            # reaping before propagating cancellation from the caller.
            await communicate
            raise
        finally:
            if process.returncode is None:
                await process.wait()
