from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from artcode.context_management.models import CompressionReport, CompressionTrigger
from artcode.conversation import ConversationContext
from artcode.prompting.assembler import PromptRequest, PromptRequestAssembler
from artcode.providers.events import TokenUsage
from artcode.permissions import PermissionState
from artcode.tools import ToolEnvironment, ToolRegistry, ToolRunContext

from .events import AgentEvent, context_status_event

if TYPE_CHECKING:
    from artcode.agent.modes import AgentMode
    from artcode.context_management.manager import ContextManager


class DurableSystemPromptSource(Protocol):
    def build_system_prompt(self) -> str:
        ...


@dataclass(frozen=True)
class AgentRunRequest:
    user_content: str
    mode: AgentMode
    max_iterations: int | None = None
    append_user_message: bool = True
    final_summary_on_abnormal_stop: bool = True

    def __post_init__(self) -> None:
        value = self.max_iterations
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int) or value <= 0
        ):
            raise ValueError("max_iterations must be a positive integer or None")


@dataclass(frozen=True)
class PreparedModelRequest:
    request: PromptRequest | None
    events: tuple[AgentEvent, ...] = ()
    error_message: str = ""
    consumes_resume_reminder: bool = False


class RequestPreparer:
    """Coordinates request preparation while keeping prompt assembly pure."""

    def __init__(
        self,
        conversation: ConversationContext,
        assembler: PromptRequestAssembler,
        tool_registry: ToolRegistry,
        tool_environment: ToolEnvironment,
        permission_state: PermissionState,
        *,
        context_manager: ContextManager | None = None,
        durable_prompt: DurableSystemPromptSource | None = None,
        resume_reminder_required: bool = False,
    ) -> None:
        self.conversation = conversation
        self.assembler = assembler
        self.tool_registry = tool_registry
        self.tool_environment = tool_environment
        self.permission_state = permission_state
        self.context_manager = context_manager
        self.durable_prompt = durable_prompt
        self._resume_reminder_pending = resume_reminder_required

    @property
    def resume_reminder_pending(self) -> bool:
        return self._resume_reminder_pending

    def require_resume_reminder(self) -> None:
        self._resume_reminder_pending = True

    def preview_request(
        self,
        mode: AgentMode | None,
        *,
        include_tools: bool = True,
    ) -> PromptRequest:
        return self._assemble(mode, include_tools=include_tools)

    def estimate(self, mode: AgentMode | None, *, include_tools: bool = True) -> int | None:
        if self.context_manager is None:
            return None
        return self.context_manager.estimate_request(
            self.preview_request(mode, include_tools=include_tools)
        )

    async def prepare(
        self,
        mode: AgentMode | None,
        *,
        include_tools: bool = True,
    ) -> PreparedModelRequest:
        events: list[AgentEvent] = []
        persisted_count = 0
        if self.context_manager is not None:
            lightweight = self.context_manager.run_lightweight(self.conversation)
            persisted_count = lightweight.persisted_count
            if lightweight.persisted_count or lightweight.failures:
                events.append(self.lightweight_event(lightweight))

        request = self._assemble(mode, include_tools=include_tools)
        if self.context_manager is None:
            return self._prepared(request, events)

        estimated = self.context_manager.estimate_request(request)
        if self.context_manager.unsafe_persistence_failure(self.conversation, estimated):
            events.append(
                context_status_event(
                    "lightweight",
                    "blocked",
                    estimated,
                    estimated,
                    persisted_count,
                    self.context_manager.circuit.open,
                    "工具结果存盘失败，继续请求会越过安全边界。",
                )
            )
            return PreparedModelRequest(
                None,
                tuple(events),
                "工具结果存盘失败，模型请求未发送。",
            )

        trigger = self.context_manager.choose_trigger(estimated)
        if trigger is not None:
            report = await self.context_manager.compact(self.conversation, trigger)
            events.append(self.compression_event(report, persisted_count))
            if report.status == "blocked":
                return PreparedModelRequest(None, tuple(events), report.message)
            if report.status == "success":
                request = self._assemble(mode, include_tools=include_tools)
        return self._prepared(request, events)

    async def prepare_emergency_retry(
        self,
        mode: AgentMode | None,
        *,
        include_tools: bool = True,
    ) -> PreparedModelRequest:
        if self.context_manager is None:
            return PreparedModelRequest(None, error_message="上下文管理尚未启用。")
        report = await self.context_manager.compact(
            self.conversation,
            CompressionTrigger.EMERGENCY,
        )
        events = (self.compression_event(report),)
        if report.status != "success":
            return PreparedModelRequest(None, events, report.message)
        return self._prepared(
            self._assemble(mode, include_tools=include_tools),
            list(events),
        )

    def mark_dispatched(self, prepared: PreparedModelRequest) -> None:
        if prepared.request is None:
            raise ValueError("cannot dispatch an empty prepared request")
        if prepared.consumes_resume_reminder:
            self._resume_reminder_pending = False

    def record_usage(self, usage: TokenUsage | None, request: PromptRequest) -> None:
        if self.context_manager is not None:
            self.context_manager.record_usage(usage, request)

    def _assemble(self, mode: AgentMode | None, *, include_tools: bool) -> PromptRequest:
        tools = (
            self.tool_registry.openai_tools(include_internal_metadata=True)
            if include_tools
            else None
        )
        durable = self.durable_prompt.build_system_prompt() if self.durable_prompt else None
        run_context = (
            ToolRunContext(
                self.tool_environment,
                mode,
                self.permission_state.snapshot(),
            )
            if mode is not None
            else self.tool_environment
        )
        return self.assembler.assemble(
            self.conversation.export_messages(),
            mode,
            tools,
            run_context,
            durable_system_prompt=durable,
            include_resume_reminder=self._resume_reminder_pending,
        )

    @staticmethod
    def _prepared(
        request: PromptRequest,
        events: list[AgentEvent],
    ) -> PreparedModelRequest:
        return PreparedModelRequest(
            request,
            tuple(events),
            consumes_resume_reminder=request.includes_resume_reminder,
        )

    def lightweight_event(self, report) -> AgentEvent:
        message = "; ".join(failure.message for failure in report.failures)
        return context_status_event(
            "lightweight",
            "failed" if report.failures else "success",
            report.before_tokens,
            report.after_tokens,
            report.persisted_count,
            bool(self.context_manager and self.context_manager.circuit.open),
            message,
        )

    def compression_event(
        self,
        report: CompressionReport,
        persisted_count: int = 0,
    ) -> AgentEvent:
        return context_status_event(
            report.trigger.value,
            report.status,
            report.before_tokens,
            report.after_tokens,
            persisted_count or report.persisted_count,
            report.circuit_open,
            report.message,
        )
