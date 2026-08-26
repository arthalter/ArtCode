from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable

from .manager import WorktreeManager


class WorktreeCleanupService:
    """Runs one startup scan and then scans managed worktrees hourly."""

    def __init__(
        self,
        manager: WorktreeManager,
        active_task_ids: Callable[[], Iterable[str]],
        *,
        interval_seconds: float = 60 * 60,
        max_age_seconds: float = 24 * 60 * 60,
    ) -> None:
        if interval_seconds <= 0 or max_age_seconds <= 0:
            raise ValueError("Worktree 清理周期和过期时间必须为正数。")
        self.manager = manager
        self.active_task_ids = active_task_ids
        self.interval_seconds = interval_seconds
        self.max_age_seconds = max_age_seconds
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self.last_removed: tuple[str, ...] = ()

    async def start(self) -> None:
        if self._task is not None:
            raise RuntimeError("Worktree 清理服务已经启动。")
        self.run_once()
        self._task = asyncio.create_task(
            self._run_periodically(), name="artcode-worktree-cleanup"
        )

    def run_once(self) -> tuple[str, ...]:
        self.last_removed = self.manager.cleanup_expired(
            self.active_task_ids(), max_age_seconds=self.max_age_seconds
        )
        return self.last_removed

    async def close(self) -> None:
        self._stop.set()
        task = self._task
        self._task = None
        if task is None:
            return
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def _run_periodically(self) -> None:
        try:
            while True:
                try:
                    await asyncio.wait_for(
                        self._stop.wait(), timeout=self.interval_seconds
                    )
                except TimeoutError:
                    self.run_once()
                    continue
                return
        except asyncio.CancelledError:
            return
