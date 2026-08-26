from __future__ import annotations

import asyncio
import inspect
import time
import uuid
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .models import (
    BackgroundTaskDetail,
    BackgroundTaskStatus,
    BackgroundTaskSummary,
    ensure_transition,
    is_terminal,
)

if TYPE_CHECKING:
    from artcode.subagents.models import AgentCreateRequest, SubagentResult


TaskRunner = Callable[[str], Awaitable["SubagentResult"]]
CompletionCallback = Callable[[BackgroundTaskDetail], object]


@dataclass
class _Record:
    task_id: str
    request: AgentCreateRequest
    worktree_required: bool
    queued_at: float
    runner: TaskRunner
    background: bool
    notify_on_completion: bool
    status: BackgroundTaskStatus = BackgroundTaskStatus.QUEUED
    started_at: float | None = None
    finished_at: float | None = None
    result: SubagentResult | None = None
    error_message: str = ""
    completion_index: int | None = None
    task: asyncio.Task[None] | None = None
    promoted: asyncio.Event = field(default_factory=asyncio.Event)


class BackgroundTaskManager:
    """A small, deterministic in-process queue with immutable public views."""

    def __init__(
        self,
        *,
        max_concurrent: int = 4,
        on_completed: CompletionCallback | None = None,
        clock: Callable[[], float] = time.monotonic,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        if max_concurrent != 4:
            raise ValueError("background task concurrency is fixed at 4")
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._on_completed = on_completed
        self._clock = clock
        self._records: dict[str, _Record] = {}
        self._completion_counter = 0
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex[:8])

    def submit(
        self,
        request: AgentCreateRequest,
        runner: TaskRunner,
        *,
        worktree_required: bool,
        notify_on_completion: bool | None = None,
    ) -> BackgroundTaskSummary:
        task_id = self._new_task_id()
        background = bool(request.background)
        record = _Record(
            task_id,
            request,
            worktree_required,
            self._clock(),
            runner,
            background,
            background if notify_on_completion is None else notify_on_completion,
        )
        self._records[task_id] = record
        record.task = asyncio.create_task(self._execute(record), name=f"artcode-{task_id}")
        return self._summary(record)

    def list(self) -> tuple[BackgroundTaskSummary, ...]:
        return tuple(self._summary(record) for record in self._records.values())

    def get(self, task_id: str) -> BackgroundTaskDetail | None:
        record = self._records.get(task_id)
        return None if record is None else self._detail(record)

    async def wait(self, task_id: str, timeout: float | None = None) -> BackgroundTaskDetail | None:
        record = self._records.get(task_id)
        if record is None or record.task is None:
            return None
        try:
            await asyncio.wait_for(asyncio.shield(record.task), timeout=timeout)
        except TimeoutError:
            pass
        except asyncio.CancelledError:
            if not record.task.done():
                raise
        return self._detail(record)

    async def wait_foreground(
        self,
        task_id: str,
        timeout: float,
    ) -> BackgroundTaskDetail | None:
        """Wait for completion, manual promotion, or the foreground deadline."""

        record = self._records.get(task_id)
        if record is None or record.task is None:
            return None
        if record.background or record.task.done():
            return self._detail(record)
        promoted = asyncio.create_task(record.promoted.wait())
        try:
            await asyncio.wait(
                (record.task, promoted),
                timeout=timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            promoted.cancel()
            await asyncio.gather(promoted, return_exceptions=True)
        return self._detail(record)

    def cancel(self, task_id: str) -> bool:
        record = self._records.get(task_id)
        if record is None or is_terminal(record.status):
            return False
        if record.status is BackgroundTaskStatus.QUEUED:
            self._set_status(record, BackgroundTaskStatus.CANCELLED)
            if record.task is not None:
                record.task.cancel()
            self._complete(record)
            return True
        if record.task is not None:
            record.task.cancel()
        return True

    def promote_to_background(self, task_id: str) -> bool:
        record = self._records.get(task_id)
        if record is None or is_terminal(record.status):
            return False
        record.background = True
        record.notify_on_completion = True
        record.promoted.set()
        return True

    def promote_current_foreground(self) -> str | None:
        for record in reversed(tuple(self._records.values())):
            if not record.background and not is_terminal(record.status):
                if self.promote_to_background(record.task_id):
                    return record.task_id
        return None

    @property
    def foreground_task_id(self) -> str | None:
        for record in reversed(tuple(self._records.values())):
            if not record.background and not is_terminal(record.status):
                return record.task_id
        return None

    def active(self) -> tuple[BackgroundTaskSummary, ...]:
        return tuple(item for item in self.list() if not is_terminal(item.status))

    async def close(self) -> None:
        for record in self._records.values():
            if not is_terminal(record.status) and record.task is not None:
                record.task.cancel()
        pending = [item.task for item in self._records.values() if item.task is not None]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    async def wait_all(self) -> None:
        pending = [
            record.task
            for record in self._records.values()
            if record.task is not None and not record.task.done()
        ]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    async def cancel_all(self) -> None:
        for task_id in tuple(self._records):
            self.cancel(task_id)
        await self.wait_all()

    async def _execute(self, record: _Record) -> None:
        acquired = False
        try:
            await self._semaphore.acquire()
            acquired = True
            if record.status is BackgroundTaskStatus.CANCELLED:
                return
            self._set_status(record, BackgroundTaskStatus.RUNNING)
            result = await record.runner(record.task_id)
            record.result = result
            if result.stop_reason.value == "natural":
                self._set_status(record, BackgroundTaskStatus.COMPLETED)
            elif result.stop_reason.value == "max_rounds":
                self._set_status(record, BackgroundTaskStatus.MAX_ROUNDS)
            elif result.stop_reason.value == "cancelled":
                self._set_status(record, BackgroundTaskStatus.CANCELLED)
            else:
                self._set_status(record, BackgroundTaskStatus.FAILED)
                record.error_message = result.error_message
        except asyncio.CancelledError:
            if not is_terminal(record.status):
                self._set_status(record, BackgroundTaskStatus.CANCELLED)
            raise
        except Exception as exc:
            if not is_terminal(record.status):
                self._set_status(record, BackgroundTaskStatus.FAILED)
            record.error_message = str(exc)
        finally:
            if acquired:
                self._semaphore.release()
            if is_terminal(record.status):
                self._complete(record)

    def _set_status(self, record: _Record, status: BackgroundTaskStatus) -> None:
        if record.status is status:
            return
        ensure_transition(record.status, status)
        record.status = status
        now = self._clock()
        if status is BackgroundTaskStatus.RUNNING:
            record.started_at = now
        elif is_terminal(status):
            record.finished_at = now

    def _complete(self, record: _Record) -> None:
        if record.completion_index is not None:
            return
        self._completion_counter += 1
        record.completion_index = self._completion_counter
        if self._on_completed is None or not record.notify_on_completion:
            return
        try:
            callback_result = self._on_completed(self._detail(record))
            if inspect.isawaitable(callback_result):
                asyncio.create_task(callback_result)
        except Exception:
            # Observation failures must not turn a completed task into failure.
            return

    def _summary(self, record: _Record) -> BackgroundTaskSummary:
        path = None
        retained = None
        if record.result is not None and record.result.handoff is not None:
            raw = getattr(record.result.handoff, "path", None)
            path = None if raw is None else str(raw)
            retained = getattr(record.result.handoff, "retained", None)
        return BackgroundTaskSummary(
            task_id=record.task_id,
            kind=record.request.kind.value,
            role_name=record.request.role_name,
            status=record.status,
            background=record.background,
            queued_at=record.queued_at,
            started_at=record.started_at,
            finished_at=record.finished_at,
            worktree_required=record.worktree_required,
            worktree_path=path,
            worktree_retained=retained,
        )

    def _detail(self, record: _Record) -> BackgroundTaskDetail:
        return BackgroundTaskDetail(
            **self._summary(record).__dict__,
            request=record.request,
            result=record.result,
            error_message=record.error_message,
            completion_index=record.completion_index,
        )

    def _new_task_id(self) -> str:
        for _ in range(100):
            suffix = self._id_factory()
            if not isinstance(suffix, str) or not re.fullmatch(r"[0-9a-f]{8}", suffix):
                raise ValueError("task id factory must return 8 lowercase hexadecimal characters")
            task_id = f"task-{suffix}"
            if task_id not in self._records:
                return task_id
        raise RuntimeError("unable to allocate a unique task id after 100 attempts")
