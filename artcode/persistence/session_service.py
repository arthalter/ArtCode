from __future__ import annotations

from datetime import datetime, timezone

from artcode.agent.memory import PlanMemory
from artcode.conversation import ConversationContext

from .models import (
    CleanupReport,
    PersistenceStatus,
    SessionContext,
    SessionDescriptor,
    SessionSelection,
    SessionSelectionMode,
    SessionRecoveryReport,
)
from .paths import DurablePaths
from .sessions import (
    SESSION_ID_RE,
    SessionCatalog,
    SessionError,
    SessionJournal,
    SessionLockedError,
    SessionRecovery,
)


class SessionService:
    """Own session selection, locking, journaling, recovery, and cleanup.

    JSONL parsing deliberately remains in ``sessions.py``.  The service only
    selects a journal and turns a recovery report into live session state.
    """

    def __init__(self, paths: DurablePaths) -> None:
        self.paths = paths
        self.catalog = SessionCatalog(paths.sessions_dir)
        self._journal: SessionJournal | None = None
        self._context: SessionContext | None = None
        self._closed = False

    @property
    def journal(self) -> SessionJournal:
        if self._journal is None:
            raise SessionError("会话服务尚未启动。")
        return self._journal

    @property
    def context(self) -> SessionContext:
        if self._context is None:
            raise SessionError("会话服务尚未启动。")
        return self._context

    @property
    def status(self) -> PersistenceStatus:
        return self.context.status

    def start(
        self,
        selection: SessionSelection | None = None,
        now: datetime | None = None,
    ) -> SessionContext:
        if self._closed:
            raise SessionError("已经关闭的会话服务不能重新启动。")
        if self._journal is not None:
            raise SessionError("会话服务不能重复启动。")

        current = now or datetime.now(timezone.utc)
        selected = selection or SessionSelection.latest()
        self.catalog.cleanup_expired(current)
        journal, recovery, restored, default_locked_new = self._select(
            selected, current
        )
        try:
            if recovery is None:
                conversation = ConversationContext(observer=journal)
                plan_memory = PlanMemory()
                recovered_messages = 0
                bad_lines = 0
                truncated = False
                truncated_reason = ""
                resume_reminder_required = False
            else:
                conversation = ConversationContext.from_persisted_records(
                    recovery.records,
                    observer=journal,
                )
                plan_memory = PlanMemory(recovery.recovered_plan)
                recovered_messages = len(recovery.records)
                bad_lines = recovery.bad_line_count
                truncated = recovery.truncated
                truncated_reason = recovery.truncated_reason
                resume_reminder_required = recovery.gap_reminder_required

            status = PersistenceStatus(
                session_id=journal.session_id,
                restored=restored,
                recovered_messages=recovered_messages,
                bad_line_count=bad_lines,
                truncated=truncated,
                truncated_reason=truncated_reason,
                default_locked_new_session=default_locked_new,
            )
            context = SessionContext(
                conversation,
                plan_memory,
                status,
                resume_reminder_required,
            )
            self._journal = journal
            self._context = context
            return context
        except Exception:
            journal.close()
            raise

    def sessions_summary(self, limit: int = 20) -> tuple[SessionDescriptor, ...]:
        return self.catalog.list_recent(limit)

    def cleanup_expired(self, now: datetime | None = None) -> CleanupReport:
        return self.catalog.cleanup_expired(now)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._journal is not None:
            self._journal.close()

    def _select(
        self,
        selected: SessionSelection,
        current: datetime,
    ) -> tuple[SessionJournal, SessionRecoveryReport | None, bool, bool]:
        journal: SessionJournal | None = None
        try:
            if selected.mode is SessionSelectionMode.NEW:
                journal = SessionJournal.create(self.paths.sessions_dir, current)
                return journal, None, False, False

            if selected.mode is SessionSelectionMode.RESUME:
                session_id = selected.session_id or ""
                if not SESSION_ID_RE.fullmatch(session_id):
                    raise SessionError("显式恢复的会话 ID 格式非法。")
                descriptor = self.catalog.get(session_id)
                if descriptor is None:
                    raise SessionError(f"找不到会话：{session_id}")
                journal = SessionJournal.open_existing(descriptor.path)
                recovery = SessionRecovery().recover(journal, current)
                return journal, recovery, True, False

            recent = self.catalog.list_recent(limit=1)
            if not recent:
                journal = SessionJournal.create(self.paths.sessions_dir, current)
                return journal, None, False, False
            if recent[0].locked:
                journal = SessionJournal.create(self.paths.sessions_dir, current)
                return journal, None, False, True
            try:
                journal = SessionJournal.open_existing(recent[0].path)
            except SessionLockedError:
                journal = SessionJournal.create(self.paths.sessions_dir, current)
                return journal, None, False, True
            recovery = SessionRecovery().recover(journal, current)
            return journal, recovery, True, False
        except Exception:
            if journal is not None:
                journal.close()
            raise
