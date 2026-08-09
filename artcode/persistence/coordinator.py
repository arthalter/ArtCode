from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from artcode.agent.memory import PlanMemory
from artcode.context_management.models import CompressionTrigger
from artcode.conversation import ConversationContext
from artcode.prompting.builder import PromptBuilder
from artcode.prompting.sections import (
    default_fixed_sections,
    durable_instruction_sections,
    durable_memory_section,
)

from artcode.providers.base import StreamingProvider
from artcode.workspace import ArtCodePaths, Workspace

from .instructions import InstructionLoader
from .models import (
    InstructionBundle,
    MemoryScope,
    MemoryUpdateReport,
    PersistenceStatus,
    RestorePreparationReport,
    SessionSelection,
    SessionSelectionMode,
)
from .notes import MemoryNoteStore
from .paths import DurablePaths
from .sessions import (
    SESSION_ID_RE,
    SessionCatalog,
    SessionError,
    SessionJournal,
    SessionLockedError,
    SessionRecovery,
)
from .updater import MemoryUpdater, MemoryUpdateWorker

if TYPE_CHECKING:
    from artcode.agent.modes import AgentMode
    from artcode.agent.request import RequestPreparer
    from artcode.context_management.manager import ContextManager


class DurablePromptContext:
    def __init__(
        self,
        instructions: InstructionBundle,
        user_notes: MemoryNoteStore,
        project_notes: MemoryNoteStore,
    ) -> None:
        self.instructions = instructions
        self.user_notes = user_notes
        self.project_notes = project_notes

    def build_system_prompt(self) -> str:
        optional = [*durable_instruction_sections(self.instructions)]
        optional.append(
            durable_memory_section(
                self.user_notes.read_index(),
                self.project_notes.read_index(),
            )
        )
        return PromptBuilder().build(default_fixed_sections(), optional)


class PersistenceCoordinator:
    def __init__(
        self,
        *,
        paths: DurablePaths,
        catalog: SessionCatalog,
        instructions: InstructionBundle,
        user_notes: MemoryNoteStore,
        project_notes: MemoryNoteStore,
        journal: SessionJournal,
        conversation: ConversationContext,
        plan_memory: PlanMemory,
        prompt_context: DurablePromptContext,
        memory_worker: MemoryUpdateWorker,
        status: PersistenceStatus,
        gap_reminder_required: bool,
    ) -> None:
        self.paths = paths
        self.catalog = catalog
        self.instructions = instructions
        self.user_notes = user_notes
        self.project_notes = project_notes
        self.journal = journal
        self.conversation = conversation
        self.plan_memory = plan_memory
        self.prompt_context = prompt_context
        self.memory_worker = memory_worker
        self.status = status
        self.gap_reminder_required = gap_reminder_required
        self.last_memory_report: MemoryUpdateReport | None = None
        self._memory_callbacks: list[Any] = []
        self._restore_prepared = False
        self._closed = False

    @classmethod
    def start(
        cls,
        app_paths: ArtCodePaths,
        workspace: Workspace,
        provider: StreamingProvider,
        selection: SessionSelection | None = None,
        now: datetime | None = None,
        *,
        secrets: tuple[str, ...] = (),
    ) -> "PersistenceCoordinator":
        current = now or datetime.now(timezone.utc)
        selected = selection or SessionSelection.latest()
        paths = DurablePaths.from_context(app_paths, workspace)
        catalog = SessionCatalog(paths.sessions_dir)
        catalog.cleanup_expired(current)
        instructions = InstructionLoader(paths).load()
        user_notes = MemoryNoteStore(paths.user_memory_dir, MemoryScope.USER)
        project_notes = MemoryNoteStore(paths.project_memory_dir, MemoryScope.PROJECT)
        user_index = user_notes.rebuild_index()
        project_index = project_notes.rebuild_index()

        journal, recovery, restored, default_locked_new = _select_session(
            catalog, paths, selected, current
        )

        try:
            if recovery is None:
                conversation = ConversationContext(observer=journal)
                plan_memory = PlanMemory()
                recovered_messages = bad_lines = 0
                truncated = False
                truncated_reason = ""
                gap_required = False
            else:
                conversation = ConversationContext.from_persisted_records(
                    recovery.records, observer=journal
                )
                plan_memory = PlanMemory(recovery.recovered_plan)
                recovered_messages = len(recovery.records)
                bad_lines = recovery.bad_line_count
                truncated = recovery.truncated
                truncated_reason = recovery.truncated_reason
                gap_required = recovery.gap_reminder_required
            prompt_context = DurablePromptContext(instructions, user_notes, project_notes)
            updater = MemoryUpdater(
                provider,
                user_notes,
                project_notes,
                secrets=secrets,
            )
            worker = MemoryUpdateWorker(updater)
            status = PersistenceStatus(
                journal.session_id,
                restored,
                recovered_messages,
                bad_lines,
                truncated,
                truncated_reason,
                instructions.total_bytes,
                len(instructions.issues),
                user_index.active_count,
                project_index.active_count,
                default_locked_new,
            )
            coordinator = cls(
                paths=paths,
                catalog=catalog,
                instructions=instructions,
                user_notes=user_notes,
                project_notes=project_notes,
                journal=journal,
                conversation=conversation,
                plan_memory=plan_memory,
                prompt_context=prompt_context,
                memory_worker=worker,
                status=status,
                gap_reminder_required=gap_required,
            )
            worker.callback = coordinator._on_memory_report
            return coordinator
        except Exception:
            journal.close()
            raise

    @property
    def turn_observer(self) -> MemoryUpdateWorker:
        return self.memory_worker

    async def prepare_restored_context(
        self,
        context_manager: "ContextManager",
        preparer: "RequestPreparer",
        mode: "AgentMode",
    ) -> RestorePreparationReport:
        if self._restore_prepared:
            return RestorePreparationReport(False, "already_prepared")
        self._restore_prepared = True
        report = RestorePreparationReport()
        if self.status.restored and self.status.recovered_messages:
            context_manager.run_lightweight(self.conversation)
            request = preparer.preview_request(mode, include_tools=True)
            estimated = context_manager.estimate_request(request)
            if estimated >= context_manager.config.automatic_threshold:
                compressed = await context_manager.compact(
                    self.conversation, CompressionTrigger.RESTORE
                )
                report = RestorePreparationReport(
                    True,
                    compressed.status,
                    compressed.before_tokens,
                    compressed.after_tokens,
                    compressed.message,
                )
            else:
                report = RestorePreparationReport(
                    False, "not_needed", estimated, estimated
                )
        if self.gap_reminder_required:
            preparer.require_resume_reminder()
        return report

    def sessions_summary(self, limit: int = 20) -> tuple[Any, ...]:
        return self.catalog.list_recent(limit)

    def memory_summary(self) -> dict[str, Any]:
        user = self.user_notes.scan()
        project = self.project_notes.scan()
        return {
            "user_path": self.user_notes.root,
            "project_path": self.project_notes.root,
            "user_active": sum(note.status.value == "active" for note in user.notes),
            "project_active": sum(note.status.value == "active" for note in project.notes),
            "user_superseded": sum(note.status.value == "superseded" for note in user.notes),
            "project_superseded": sum(note.status.value == "superseded" for note in project.notes),
            "user_issues": len(user.issues),
            "project_issues": len(project.issues),
            "last_report": self.last_memory_report,
        }

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self.memory_worker.close()
        self.journal.close()

    def add_memory_callback(self, callback: Any) -> None:
        self._memory_callbacks.append(callback)

    def _on_memory_report(self, report: MemoryUpdateReport) -> None:
        self.last_memory_report = report
        for callback in tuple(self._memory_callbacks):
            try:
                callback(report)
            except Exception:
                continue


def _select_session(
    catalog: SessionCatalog,
    paths: DurablePaths,
    selected: SessionSelection,
    current: datetime,
) -> tuple[SessionJournal, Any, bool, bool]:
    journal: SessionJournal | None = None
    try:
        if selected.mode is SessionSelectionMode.NEW:
            journal = SessionJournal.create(paths.sessions_dir, current)
            return journal, None, False, False
        if selected.mode is SessionSelectionMode.RESUME:
            session_id = selected.session_id or ""
            if not SESSION_ID_RE.fullmatch(session_id):
                raise SessionError("显式恢复的会话 ID 格式非法。")
            descriptor = catalog.get(session_id)
            if descriptor is None:
                raise SessionError(f"找不到会话：{session_id}")
            journal = SessionJournal.open_existing(descriptor.path)
            recovery = SessionRecovery().recover(journal, current)
            return journal, recovery, True, False

        recent = catalog.list_recent(limit=1)
        if not recent:
            journal = SessionJournal.create(paths.sessions_dir, current)
            return journal, None, False, False
        if recent[0].locked:
            journal = SessionJournal.create(paths.sessions_dir, current)
            return journal, None, False, True
        try:
            journal = SessionJournal.open_existing(recent[0].path)
        except SessionLockedError:
            journal = SessionJournal.create(paths.sessions_dir, current)
            return journal, None, False, True
        recovery = SessionRecovery().recover(journal, current)
        return journal, recovery, True, False
    except Exception:
        if journal is not None:
            journal.close()
        raise
