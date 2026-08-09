from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from artcode.agent.memory import PlanMemory
from artcode.context_management.models import CompressionTrigger
from artcode.conversation import ConversationContext
from artcode.prompting.builder import PromptBuilder
from artcode.prompting.durable import DurablePromptSource
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
    MemoryUpdateReport,
    PersistenceStatus,
    RestorePreparationReport,
    SessionSelection,
)
from .memory_service import MemoryService
from .notes import MemoryNoteStore
from .paths import DurablePaths
from .session_service import SessionService
from .sessions import SessionCatalog, SessionJournal
from .updater import MemoryUpdateWorker

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
        session_service: SessionService,
        memory_service: MemoryService,
        prompt_source: DurablePromptSource,
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
        self.session_service = session_service
        self.memory_service = memory_service
        self.prompt_source = prompt_source
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
        session_service = SessionService(paths)
        try:
            session = session_service.start(selected, current)
            memory_service = MemoryService(
                paths,
                provider,
                secrets=secrets,
            )
            prompt_source = DurablePromptSource(paths)
            status = replace(
                session.status,
                instruction_bytes=prompt_source.instructions.total_bytes,
                instruction_issues=len(prompt_source.instructions.issues),
                user_active_notes=memory_service.user_index_report.active_count,
                project_active_notes=memory_service.project_index_report.active_count,
            )
            coordinator = cls(
                paths=paths,
                catalog=session_service.catalog,
                instructions=prompt_source.instructions,
                user_notes=memory_service.user_store,
                project_notes=memory_service.project_store,
                journal=session_service.journal,
                conversation=session.conversation,
                plan_memory=session.plan_memory,
                prompt_context=prompt_source,
                memory_worker=memory_service.worker,
                status=status,
                gap_reminder_required=session.resume_reminder_required,
                session_service=session_service,
                memory_service=memory_service,
                prompt_source=prompt_source,
            )
            memory_service.add_callback(coordinator._on_memory_report)
            return coordinator
        except Exception:
            session_service.close()
            raise

    @property
    def turn_observer(self) -> MemoryService:
        return self.memory_service

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
        return self.session_service.sessions_summary(limit)

    def memory_summary(self) -> dict[str, Any]:
        return self.memory_service.summary()

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self.memory_service.close()
        self.session_service.close()

    def add_memory_callback(self, callback: Any) -> None:
        self._memory_callbacks.append(callback)

    def _on_memory_report(self, report: MemoryUpdateReport) -> None:
        self.last_memory_report = report
        for callback in tuple(self._memory_callbacks):
            try:
                callback(report)
            except Exception:
                continue
