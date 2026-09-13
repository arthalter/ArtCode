from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import os
from pathlib import Path
import signal


@dataclass(frozen=True, slots=True)
class RawProcessOutcome:
    argv: tuple[str, ...]
    returncode: int | None
    stdout: bytes = b""
    stderr: bytes = b""
    timed_out: bool = False
    cancelled: bool = False
    start_error: str | None = None


@dataclass(slots=True)
class _Running:
    process: asyncio.subprocess.Process
    communicate: asyncio.Task[tuple[bytes, bytes]]


class ProcessSupervisor:
    def __init__(self) -> None:
        self._running: dict[int, _Running] = {}
        self._closed_pids: set[int] = set()
        self._closed = False

    @property
    def active_count(self) -> int:
        return len(self._running)

    async def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        environment: Mapping[str, str],
        timeout_seconds: float,
    ) -> RawProcessOutcome:
        if self._closed:
            raise RuntimeError("进程管理器已关闭。")
        selected = tuple(str(item) for item in argv)
        if not selected or any(not item for item in selected):
            raise ValueError("进程 argv 必须包含非空参数。")
        if timeout_seconds <= 0:
            raise ValueError("进程超时必须为正数。")
        try:
            process = await asyncio.create_subprocess_exec(
                *selected,
                cwd=str(cwd),
                env=dict(environment),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
        except asyncio.CancelledError:
            raise
        except (OSError, TypeError, ValueError) as exc:
            return RawProcessOutcome(selected, None, start_error=str(exc))

        communicate = asyncio.create_task(process.communicate())
        running = _Running(process, communicate)
        self._running[process.pid] = running
        try:
            try:
                stdout, stderr = await asyncio.wait_for(
                    asyncio.shield(communicate), timeout=timeout_seconds
                )
            except TimeoutError:
                await self._kill_and_reap(running)
                stdout, stderr = communicate.result()
                return RawProcessOutcome(
                    selected, process.returncode, stdout, stderr, timed_out=True
                )
            except asyncio.CancelledError:
                await self._kill_and_reap(running)
                raise
            except BaseException:
                await self._kill_and_reap(running)
                raise
            return RawProcessOutcome(
                selected,
                process.returncode,
                stdout,
                stderr,
                cancelled=process.pid in self._closed_pids,
            )
        finally:
            self._running.pop(process.pid, None)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        running = tuple(self._running.values())
        self._closed_pids.update(item.process.pid for item in running)
        await asyncio.gather(*(self._kill_and_reap(item) for item in running))
        for _ in range(10):
            if not self._running:
                break
            await asyncio.sleep(0)

    async def _kill_and_reap(self, running: _Running) -> None:
        process = running.process
        if process.returncode is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        try:
            await asyncio.shield(running.communicate)
        except asyncio.CancelledError:
            await running.communicate
            raise
        finally:
            if process.returncode is None:
                await process.wait()
