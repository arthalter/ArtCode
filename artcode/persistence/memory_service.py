from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from artcode.agent.events import CompletedTurn
from artcode.providers.base import StreamingProvider

from .models import MemoryScope, MemoryStatusSnapshot, MemoryUpdateReport
from .notes import MemoryNoteStore
from .paths import DurablePaths
from .updater import MemoryUpdater, MemoryUpdateWorker


class MemoryService:
    """Own both durable note stores and their single-consumer update worker."""

    def __init__(
        self,
        paths: DurablePaths,
        provider: StreamingProvider,
        *,
        secrets: Sequence[str] = (),
        updater: MemoryUpdater | None = None,
    ) -> None:
        self.paths = paths
        self.user_store = MemoryNoteStore(paths.user_memory_dir, MemoryScope.USER)
        self.project_store = MemoryNoteStore(paths.project_memory_dir, MemoryScope.PROJECT)
        self.user_index_report = self.user_store.rebuild_index()
        self.project_index_report = self.project_store.rebuild_index()
        self.updater = updater or MemoryUpdater(
            provider,
            self.user_store,
            self.project_store,
            secrets=secrets,
        )
        self.worker = MemoryUpdateWorker(self.updater, self._publish)
        self._callbacks: list[Callable[[MemoryUpdateReport], Any]] = []
        self._last_report: MemoryUpdateReport | None = None

    @property
    def last_report(self) -> MemoryUpdateReport | None:
        return self._last_report

    @property
    def pending_count(self) -> int:
        return self.worker.pending_count

    def submit(self, turn: CompletedTurn) -> None:
        self.worker.submit(turn)

    def add_callback(self, callback: Callable[[MemoryUpdateReport], Any]) -> None:
        self._callbacks.append(callback)

    async def wait_idle(self) -> None:
        await self.worker.wait_idle()

    async def close(self) -> None:
        await self.worker.close()

    def status_snapshot(self) -> MemoryStatusSnapshot:
        user = self.user_store.scan()
        project = self.project_store.scan()
        return MemoryStatusSnapshot(
            user_path=self.user_store.root,
            project_path=self.project_store.root,
            user_active=sum(note.status.value == "active" for note in user.notes),
            project_active=sum(note.status.value == "active" for note in project.notes),
            user_superseded=sum(
                note.status.value == "superseded" for note in user.notes
            ),
            project_superseded=sum(
                note.status.value == "superseded" for note in project.notes
            ),
            user_issues=len(user.issues),
            project_issues=len(project.issues),
            pending_count=self.pending_count,
            last_report=self.last_report,
        )

    def summary(self) -> dict[str, Any]:
        """Transitional mapping compatibility; production uses an immutable snapshot."""

        snapshot = self.status_snapshot()
        return {
            "user_path": snapshot.user_path,
            "project_path": snapshot.project_path,
            "user_active": snapshot.user_active,
            "project_active": snapshot.project_active,
            "user_superseded": snapshot.user_superseded,
            "project_superseded": snapshot.project_superseded,
            "user_issues": snapshot.user_issues,
            "project_issues": snapshot.project_issues,
            "last_report": snapshot.last_report,
        }

    def _publish(self, report: MemoryUpdateReport) -> None:
        self._last_report = report
        for callback in tuple(self._callbacks):
            try:
                callback(report)
            except Exception:
                continue
