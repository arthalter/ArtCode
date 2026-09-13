from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable
from dataclasses import replace

from artcode.core.agent import (
    CompactionEvent,
    RunControl,
    RunError,
    RunEvent,
    RunFinished,
    RunOutcome,
    RunStarted,
    StopReason,
    TextEvent,
    ToolBatchEvent,
    UsageEvent,
)
from artcode.core.model import (
    Completed,
    ContextWindowFailure,
    Model,
    ModelEvent,
    ModelFailure,
    ModelMessage,
    ModelRequest,
    TextDelta,
    ToolRequests,
    Usage,
)
from artcode.core.session import CompactionTrigger, DispatchedRun, RunCompletion, Session
from artcode.core.tool import Approver, Tool, ToolCall

from .events import ControlledCancellation
from .usage import UsageAccumulator


class AgentRunner:
    def __init__(
        self,
        model: Model,
        tools: Tool,
        session: Session,
        *,
        approver: Approver | None = None,
        memory_model: Model | None = None,
    ) -> None:
        self.model = model
        self.tools = tools
        self.session = session
        self.approver = approver
        self.memory_model = memory_model

    async def run(
        self,
        dispatched: DispatchedRun,
        *,
        max_rounds: int | None = None,
        control: RunControl | None = None,
    ) -> AsyncIterator[RunEvent]:
        if max_rounds is not None and (
            isinstance(max_rounds, bool) or not isinstance(max_rounds, int) or max_rounds < 1
        ):
            raise ValueError("max_rounds 必须是正整数或 None。")
        control = control or RunControl()
        lease = dispatched.lease
        request = dispatched.request
        run_tools = lease.tools
        refresh_tools = False
        next_trigger = CompactionTrigger.AUTOMATIC
        context_error: ContextWindowFailure | None = None
        emergency_used = False
        request_usage: Usage | None = None
        usage = UsageAccumulator()
        rounds = 0
        tool_batches = 0
        pending_requests = None
        pending_metadata = None
        pending_text = ""
        yield RunStarted(lease.id)
        try:
            while True:
                if control.cancelled:
                    raise ControlledCancellation
                next_tools = self.tools.refresh_run(run_tools) if refresh_tools else run_tools
                preparation = await _controlled_await(
                    self.session.prepare_next_request(
                        lease, request, next_tools, model=self.model,
                        usage=request_usage, trigger=next_trigger,
                    ),
                    control,
                )
                if preparation.compaction is not None:
                    yield CompactionEvent(preparation.compaction)
                if control.cancelled:
                    raise ControlledCancellation
                recovery_failed = next_trigger is CompactionTrigger.EMERGENCY and (
                    preparation.compaction is None or preparation.compaction.status != "success"
                )
                if not preparation.can_continue or recovery_failed:
                    detail = str(context_error) if context_error is not None else preparation.detail
                    self.session.finish_run(lease, RunCompletion.FAILED, usage=usage.snapshot())
                    yield RunError("context_window", detail)
                    yield RunFinished(RunOutcome(
                        StopReason.MODEL_FAILURE if context_error is not None else StopReason.CANNOT_CONTINUE,
                        rounds, usage.snapshot(), "", tool_batches, detail,
                    ))
                    return
                request, run_tools = preparation.request, next_tools
                refresh_tools = False
                next_trigger = CompactionTrigger.AUTOMATIC
                request_usage = None
                rounds += 1
                text_parts: list[str] = []
                requested: ToolRequests | None = None
                completed: Completed | None = None
                try:
                    async for event in _controlled_stream(self.model, request, control):
                        if isinstance(event, TextDelta):
                            text_parts.append(event.text)
                            yield TextEvent(event.text)
                        elif isinstance(event, Usage):
                            request_usage = event
                            cumulative = usage.add(event)
                            yield UsageEvent(cumulative)
                        elif isinstance(event, ToolRequests):
                            if requested is not None:
                                raise ModelFailure("单次 Model 响应包含多个 Tool Request 终结事件。")
                            requested = event
                        elif isinstance(event, Completed):
                            completed = event
                except ModelFailure as exc:
                    if (
                        isinstance(exc, ContextWindowFailure)
                        and not text_parts and requested is None
                        and not emergency_used
                        and (max_rounds is None or rounds < max_rounds)
                    ):
                        context_error = exc
                        emergency_used = True
                        next_trigger = CompactionTrigger.EMERGENCY
                        continue
                    self.session.finish_run(
                        lease,
                        RunCompletion.FAILED,
                        usage=usage.snapshot(),
                    )
                    yield RunError(exc.category, str(exc))
                    yield RunFinished(
                        RunOutcome(
                            StopReason.MODEL_FAILURE,
                            rounds,
                            usage.snapshot(),
                            "".join(text_parts),
                            tool_batches,
                            str(exc),
                        )
                    )
                    return

                response_text = "".join(text_parts)
                if requested is not None:
                    pending_requests = requested.requests
                    pending_metadata = requested.metadata
                    pending_text = response_text
                    calls = tuple(
                        ToolCall(item.id, item.name, item.arguments_json)
                        for item in requested.requests
                    )
                    try:
                        results = await _controlled_await(
                            self.tools.execute_batch(
                                replace(run_tools, execution_data=request),
                                calls,
                                approver=self.approver,
                            ),
                            control,
                            preserve_completed=True,
                        )
                    except ControlledCancellation:
                        self.session.commit_tool_exchange(
                            requested.requests,
                            (),
                            metadata=requested.metadata,
                            cancelled=True,
                            assistant_text=response_text,
                        )
                        raise
                    self.session.commit_tool_exchange(
                        requested.requests,
                        results,
                        metadata=requested.metadata,
                        assistant_text=response_text,
                    )
                    # Clear pending state before yielding or preparing another
                    # request, so cancellation cannot commit this exchange twice.
                    pending_requests = pending_metadata = None
                    pending_text = ""
                    tool_batches += 1
                    yield ToolBatchEvent(requested.requests, results)
                    if control.cancelled:
                        raise ControlledCancellation
                    request = _continue_request(request, requested, results, response_text)
                    refresh_tools = True
                    emergency_used = False
                    context_error = None
                    if max_rounds is not None and rounds >= max_rounds:
                        self.session.finish_run(
                            lease,
                            RunCompletion.LIMIT,
                            usage=usage.snapshot(),
                        )
                        yield RunFinished(
                            RunOutcome(
                                StopReason.LIMIT,
                                rounds,
                                usage.snapshot(),
                                "",
                                tool_batches,
                            )
                        )
                        return
                    continue

                finish = completed.finish_reason if completed is not None else None
                if finish in {None, "stop"} and response_text:
                    if self.memory_model is not None:
                        self.session.schedule_memory_update(
                            lease,
                            RunCompletion.NATURAL,
                            response_text,
                            self.memory_model,
                        )
                    self.session.finish_run(
                        lease,
                        RunCompletion.NATURAL,
                        assistant_text=response_text,
                        usage=usage.snapshot(),
                    )
                    yield RunFinished(
                        RunOutcome(
                            StopReason.NATURAL,
                            rounds,
                            usage.snapshot(),
                            response_text,
                            tool_batches,
                        )
                    )
                    return
                if finish == "length" and response_text:
                    self.session.finish_run(
                        lease,
                        RunCompletion.LENGTH,
                        assistant_text=response_text,
                        usage=usage.snapshot(),
                    )
                    yield RunFinished(
                        RunOutcome(
                            StopReason.LENGTH,
                            rounds,
                            usage.snapshot(),
                            response_text,
                            tool_batches,
                        )
                    )
                    return
                self.session.finish_run(
                    lease,
                    RunCompletion.FAILED,
                    usage=usage.snapshot(),
                )
                yield RunFinished(
                    RunOutcome(
                        StopReason.CANNOT_CONTINUE,
                        rounds,
                        usage.snapshot(),
                        response_text,
                        tool_batches,
                        f"Model finish_reason={finish!r}",
                    )
                )
                return
        except ControlledCancellation:
            self.session.finish_run(
                lease,
                RunCompletion.CANCELLED,
                usage=usage.snapshot(),
            )
            yield RunFinished(
                RunOutcome(
                    StopReason.CANCELLED,
                    rounds,
                    usage.snapshot(),
                    pending_text,
                    tool_batches,
                )
            )
        except asyncio.CancelledError:
            if pending_requests is not None:
                self.session.commit_tool_exchange(
                    pending_requests,
                    (),
                    metadata=pending_metadata,
                    cancelled=True,
                    assistant_text=pending_text,
                )
            self.session.finish_run(
                lease,
                RunCompletion.CANCELLED,
                usage=usage.snapshot(),
            )
            raise


async def _controlled_stream(
    model: Model,
    request: ModelRequest,
    control: RunControl,
) -> AsyncIterator[ModelEvent]:
    stream = model.stream(request)
    try:
        while True:
            try:
                event = await _controlled_await(anext(stream), control)
            except StopAsyncIteration:
                return
            yield event
    finally:
        close = getattr(stream, "aclose", None)
        if callable(close):
            await close()


async def _controlled_await(
    awaitable: Awaitable, control: RunControl, *, preserve_completed: bool = False,
):
    if control.cancelled:
        if hasattr(awaitable, "close"):
            awaitable.close()
        raise ControlledCancellation
    operation = asyncio.ensure_future(awaitable)
    cancellation = asyncio.create_task(control.wait_cancelled())
    try:
        done, _ = await asyncio.wait(
            (operation, cancellation), return_when=asyncio.FIRST_COMPLETED
        )
    except asyncio.CancelledError:
        operation.cancel()
        cancellation.cancel()
        await asyncio.gather(operation, cancellation, return_exceptions=True)
        raise
    # Completed tool batches may already have produced durable effects. Keep
    # their results while ordinary model/preparation waits still honor cancel.
    if cancellation in done and not (preserve_completed and operation in done):
        operation.cancel()
        await asyncio.gather(operation, return_exceptions=True)
        raise ControlledCancellation
    cancellation.cancel()
    await asyncio.gather(cancellation, return_exceptions=True)
    return operation.result()


def _continue_request(
    request: ModelRequest,
    tool_requests: ToolRequests,
    results,
    assistant_text: str,
) -> ModelRequest:
    messages = [
        *request.prompt,
        ModelMessage(
            "assistant",
            assistant_text or None,
            tool_requests=tool_requests.requests,
            metadata=tool_requests.metadata,
        ),
        *(
            ModelMessage("tool", result.content, tool_request_id=result.call_id)
            for result in results
        ),
    ]
    return ModelRequest(
        tuple(messages),
        tools=request.tools,
        max_output_tokens=request.max_output_tokens,
        thinking_enabled=request.thinking_enabled,
        model=request.model,
    )
