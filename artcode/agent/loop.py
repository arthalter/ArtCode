from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from artcode.conversation import ConversationContext
from artcode.errors import ContextWindowExceededError, RequestError
from artcode.prompting.assembler import PromptRequest, PromptRequestAssembler
from artcode.providers.base import StreamingProvider
from artcode.tools import ToolExecutionContext, ToolRegistry, error_result
from artcode.context_management.manager import ContextManager
from artcode.context_management.models import CompressionReport, CompressionTrigger

from .events import (
    AgentEvent,
    AgentEventType,
    ModelTurn,
    StopReason,
    final_summary_started_event,
    context_status_event,
    iteration_started_event,
    model_turn_completed_event,
    run_started_event,
    stopped_event,
    tool_calls_received_event,
    tool_result_event,
)
from .memory import PlanMemory
from .modes import AgentMode, PLAN_MODE
from .stream import StreamCollector
from .tools import ToolBatchExecutor, ToolExecutionBlocked


DEFAULT_MAX_ITERATIONS = 12


@dataclass(frozen=True)
class AgentRunRequest:
    user_content: str
    mode: AgentMode
    max_iterations: int = DEFAULT_MAX_ITERATIONS
    append_user_message: bool = True
    final_summary_on_abnormal_stop: bool = True


@dataclass(frozen=True)
class AgentRunResult:
    stop_reason: StopReason
    final_text: str
    iterations_used: int
    tool_results_count: int
    saved_plan: str | None = None


class AgentLoop:
    def __init__(
        self,
        provider: StreamingProvider,
        conversation: ConversationContext,
        tool_registry: ToolRegistry,
        tool_context: ToolExecutionContext,
        plan_memory: PlanMemory | None = None,
        stream_collector: StreamCollector | None = None,
        tool_executor: ToolBatchExecutor | None = None,
        request_assembler: PromptRequestAssembler | None = None,
        context_manager: ContextManager | None = None,
    ) -> None:
        self.provider = provider
        self.conversation = conversation
        self.tool_registry = tool_registry
        self.tool_context = tool_context
        self.plan_memory = plan_memory or PlanMemory()
        self.stream_collector = stream_collector or StreamCollector()
        self.tool_executor = tool_executor or ToolBatchExecutor(tool_registry, tool_context)
        self.request_assembler = request_assembler or PromptRequestAssembler()
        self.context_manager = context_manager

    async def run(self, request: AgentRunRequest) -> AsyncIterator[AgentEvent]:
        # Repair history left by an older interrupted run before appending the
        # next user message, so tool results remain adjacent to tool_calls.
        self.conversation.repair_incomplete_tool_calls()
        if request.append_user_message:
            self.conversation.append_user(request.user_content)

        yield run_started_event(request.mode.name, request.max_iterations)

        pending_tool_calls: dict[str, Any] = {}
        try:
            for iteration in range(1, request.max_iterations + 1):
                yield iteration_started_event(iteration, request.max_iterations)
                turn = await self._collect_model_turn(request.mode)
                for event in turn.events:
                    yield event
                if turn.model_turn is None:
                    yield stopped_event(StopReason.STREAM_ERROR, turn.error_message)
                    return

                model_turn = turn.model_turn
                yield model_turn_completed_event(model_turn.text, len(model_turn.tool_calls))

                if not model_turn.tool_calls:
                    if model_turn.text:
                        self.conversation.append_assistant(model_turn.text)
                        if request.mode == PLAN_MODE:
                            self.plan_memory.save(model_turn.text)
                    yield stopped_event(StopReason.NATURAL)
                    return

                self.conversation.append_assistant_tool_call(model_turn.tool_calls)
                pending_tool_calls = {tool_call.id: tool_call for tool_call in model_turn.tool_calls}
                yield tool_calls_received_event(len(model_turn.tool_calls))

                plan = self.tool_executor.build_plan(model_turn.tool_calls, request.mode.tool_policy)
                if isinstance(plan, ToolExecutionBlocked):
                    for tool_call, result in _blocked_tool_results(model_turn.tool_calls, plan):
                        self.conversation.append_tool_result(tool_call, result)
                        pending_tool_calls.pop(tool_call.id, None)
                        yield tool_result_event(tool_call, result)
                    async for event in self._summarize_if_needed(request, plan.stop_reason):
                        yield event
                    return

                async for event in self.tool_executor.execute_plan(plan, plan_mode=request.mode == PLAN_MODE):
                    if event.type == AgentEventType.TOOL_RESULT:
                        tool_call = event.payload["tool_call"]
                        result = event.payload["result"]
                        self.conversation.append_tool_result(tool_call, result)
                        pending_tool_calls.pop(tool_call.id, None)
                    yield event

            async for event in self._summarize_if_needed(request, StopReason.ITERATION_LIMIT):
                yield event
        except asyncio.CancelledError:
            repaired = self.conversation.repair_incomplete_tool_calls(
                error_code="tool_execution_cancelled",
                message="用户取消了 Agent Loop，工具未执行或未完成。",
            )
            for tool_call, result in repaired:
                if tool_call.id in pending_tool_calls:
                    yield tool_result_event(tool_call, result)
            yield stopped_event(StopReason.USER_CANCELLED, "用户取消了当前 Agent Loop。")
            return

    async def _summarize_if_needed(
        self,
        request: AgentRunRequest,
        reason: StopReason,
    ) -> AsyncIterator[AgentEvent]:
        if not request.final_summary_on_abnormal_stop:
            yield stopped_event(reason, _stop_message(reason))
            return

        yield final_summary_started_event(reason)
        try:
            turn = await self._collect_model_turn_without_tools()
        except asyncio.CancelledError:
            yield stopped_event(StopReason.USER_CANCELLED, "用户取消了最终总结。")
            return

        for event in turn.events:
            yield event
        if turn.model_turn is not None and turn.model_turn.text:
            self.conversation.append_assistant(turn.model_turn.text)
            yield model_turn_completed_event(turn.model_turn.text, len(turn.model_turn.tool_calls))
        yield stopped_event(reason, _stop_message(reason))

    async def _collect_model_turn_without_tools(self) -> "_CollectedTurn":
        self.conversation.repair_incomplete_tool_calls()
        return await self._collect_contextual_turn(None, include_tools=False)

    async def _collect_model_turn(self, mode: AgentMode) -> "_CollectedTurn":
        self.conversation.repair_incomplete_tool_calls()
        return await self._collect_contextual_turn(mode, include_tools=True)

    async def compact_context(self) -> AsyncIterator[AgentEvent]:
        if self.context_manager is None:
            yield context_status_event(
                "manual", "noop", 0, 0, 0, False, "上下文管理尚未启用。"
            )
            return
        lightweight = self.context_manager.run_lightweight(self.conversation)
        if lightweight.persisted_count or lightweight.failures:
            yield self._lightweight_event(lightweight)
        report = await self.context_manager.compact(
            self.conversation,
            CompressionTrigger.MANUAL,
        )
        yield self._compression_event(report)

    async def _collect_contextual_turn(
        self,
        mode: AgentMode | None,
        *,
        include_tools: bool,
    ) -> "_CollectedTurn":
        prepared = await self._prepare_model_request(mode, include_tools=include_tools)
        if prepared.request is None:
            return _CollectedTurn(prepared.events, None, prepared.error_message)

        collected = await self._collect_model_turn_with_messages(
            prepared.request.messages,
            prepared.request.tools,
        )
        events = [*prepared.events, *collected.events]
        if collected.model_turn is not None:
            if self.context_manager is not None:
                self.context_manager.record_usage(collected.model_turn.usage, prepared.request)
            return _CollectedTurn(events, collected.model_turn)

        if not isinstance(collected.error, ContextWindowExceededError) or self.context_manager is None:
            return _CollectedTurn(events, None, collected.error_message, collected.error)

        emergency = await self.context_manager.compact(
            self.conversation,
            CompressionTrigger.EMERGENCY,
        )
        events.append(self._compression_event(emergency))
        if emergency.status != "success":
            return _CollectedTurn(events, None, emergency.message or collected.error_message, collected.error)

        retry_request = self._assemble_request(mode, include_tools=include_tools)
        retried = await self._collect_model_turn_with_messages(
            retry_request.messages,
            retry_request.tools,
        )
        events.extend(retried.events)
        if retried.model_turn is not None:
            self.context_manager.record_usage(retried.model_turn.usage, retry_request)
        return _CollectedTurn(
            events,
            retried.model_turn,
            retried.error_message,
            retried.error,
        )

    async def _prepare_model_request(
        self,
        mode: AgentMode | None,
        *,
        include_tools: bool,
    ) -> "_PreparedRequest":
        events: list[AgentEvent] = []
        if self.context_manager is not None:
            lightweight = self.context_manager.run_lightweight(self.conversation)
            if lightweight.persisted_count or lightweight.failures:
                events.append(self._lightweight_event(lightweight))

        request = self._assemble_request(mode, include_tools=include_tools)
        if self.context_manager is None:
            return _PreparedRequest(request, events)
        estimated = self.context_manager.estimate_request(request)
        if self.context_manager.unsafe_persistence_failure(self.conversation, estimated):
            events.append(
                context_status_event(
                    "lightweight",
                    "blocked",
                    estimated,
                    estimated,
                    lightweight.persisted_count,
                    self.context_manager.circuit.open,
                    "工具结果存盘失败，继续请求会越过安全边界。",
                )
            )
            return _PreparedRequest(None, events, "工具结果存盘失败，模型请求未发送。")

        trigger = self.context_manager.choose_trigger(estimated)
        if trigger is not None:
            report = await self.context_manager.compact(self.conversation, trigger)
            events.append(self._compression_event(report, lightweight.persisted_count))
            if report.status == "blocked":
                return _PreparedRequest(None, events, report.message)
            if report.status == "success":
                request = self._assemble_request(mode, include_tools=include_tools)
        return _PreparedRequest(request, events)

    def _assemble_request(
        self,
        mode: AgentMode | None,
        *,
        include_tools: bool,
    ) -> PromptRequest:
        if not include_tools:
            return PromptRequest(self.conversation.export_messages(), None)
        return self.request_assembler.assemble(
            self.conversation.export_messages(),
            mode,
            self.tool_registry.openai_tools(include_internal_metadata=True),
            self.tool_context,
        )

    def _lightweight_event(self, report) -> AgentEvent:
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

    def _compression_event(self, report: CompressionReport, persisted_count: int = 0) -> AgentEvent:
        return context_status_event(
            report.trigger.value,
            report.status,
            report.before_tokens,
            report.after_tokens,
            persisted_count or report.persisted_count,
            report.circuit_open,
            report.message,
        )

    async def _collect_model_turn_with_messages(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> "_CollectedTurn":
        events: list[AgentEvent] = []
        try:
            async for item in self.stream_collector.collect(self.provider, messages, tools):
                if isinstance(item, ModelTurn):
                    return _CollectedTurn(events, item)
                events.append(item)
        except asyncio.CancelledError:
            raise
        except RequestError as exc:
            return _CollectedTurn(events, None, exc.user_message, exc)
        return _CollectedTurn(events, ModelTurn("", []))


@dataclass(frozen=True)
class _CollectedTurn:
    events: list[AgentEvent]
    model_turn: ModelTurn | None
    error_message: str = ""
    error: RequestError | None = None


@dataclass(frozen=True)
class _PreparedRequest:
    request: PromptRequest | None
    events: list[AgentEvent]
    error_message: str = ""


def _stop_message(reason: StopReason) -> str:
    if reason == StopReason.ITERATION_LIMIT:
        return "Agent Loop 达到 12 轮上限。"
    if reason == StopReason.UNKNOWN_TOOL:
        return "模型请求了未知或当前模式不允许的工具。"
    if reason == StopReason.STREAM_ERROR:
        return "流式响应出错。"
    if reason == StopReason.USER_CANCELLED:
        return "用户取消了当前 Agent Loop。"
    return ""


def _blocked_tool_results(tool_calls: list[Any], blocked: ToolExecutionBlocked):
    for tool_call in tool_calls:
        if tool_call.id == blocked.tool_call.id:
            yield tool_call, blocked.result
        else:
            yield tool_call, error_result(
                tool_call.name or "unknown_tool",
                "tool_execution_blocked",
                "同一轮工具调用中出现未知或当前模式不允许的工具，本轮所有工具均未执行。",
            )
