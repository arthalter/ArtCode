from __future__ import annotations

from typing import TYPE_CHECKING

from artcode.config import ContextConfig
from artcode.conversation import ConversationContext

if TYPE_CHECKING:
    from artcode.agent.events import TokenUsage
    from artcode.prompting.assembler import PromptRequest

from .estimator import TokenEstimator
from .lightweight import LightweightCompactor
from .models import (
    AUTOMATIC_FAILURE_LIMIT,
    CompressionCircuit,
    CompressionReport,
    CompressionTrigger,
    LightweightReport,
)
from .retention import RetentionPlanner
from .summarizer import ContextSummarizer


class ContextManager:
    def __init__(
        self,
        config: ContextConfig,
        summarizer: ContextSummarizer,
        *,
        estimator: TokenEstimator | None = None,
        lightweight_compactor: LightweightCompactor | None = None,
        retention_planner: RetentionPlanner | None = None,
        circuit: CompressionCircuit | None = None,
    ) -> None:
        self.config = config
        self.summarizer = summarizer
        self.estimator = estimator or TokenEstimator()
        self.lightweight_compactor = lightweight_compactor
        self.retention_planner = retention_planner or RetentionPlanner()
        self.circuit = circuit or CompressionCircuit()

    def run_lightweight(self, conversation: ConversationContext) -> LightweightReport:
        if self.lightweight_compactor is None:
            return LightweightReport()
        return self.lightweight_compactor.apply(conversation)

    def estimate_request(self, request: PromptRequest) -> int:
        return self.estimator.estimate_request(request.messages, request.tools)

    def choose_trigger(self, estimated_tokens: int) -> CompressionTrigger | None:
        if estimated_tokens >= self.config.forced_threshold:
            if not self.circuit.forced_attempted:
                return CompressionTrigger.FORCED
            return None
        if estimated_tokens >= self.config.automatic_threshold and not self.circuit.open:
            return CompressionTrigger.AUTOMATIC
        return None

    async def compact(
        self,
        conversation: ConversationContext,
        trigger: CompressionTrigger,
    ) -> CompressionReport:
        before = self.estimator.estimate_request(conversation.export_messages(), None)
        snapshot = conversation.snapshot()
        plan = self.retention_planner.plan(snapshot)
        if not plan.can_compact:
            return CompressionReport(
                trigger,
                "noop",
                before,
                before,
                circuit_open=self.circuit.open,
                message="没有可压缩的较早历史。",
            )

        if trigger is CompressionTrigger.FORCED:
            self.circuit.forced_attempted = True
        result = await self.summarizer.summarize(snapshot, plan)
        after = self.estimator.estimate_request(conversation.export_messages(), None)
        if result.succeeded:
            self.circuit.reset()
            return CompressionReport(
                trigger,
                "success",
                before,
                after,
                circuit_open=False,
            )
        if result.status == "noop":
            return CompressionReport(
                trigger,
                "noop",
                before,
                after,
                circuit_open=self.circuit.open,
                message=result.message,
            )

        if trigger in {CompressionTrigger.AUTOMATIC, CompressionTrigger.FORCED}:
            self.circuit.consecutive_failures += 1
            if self.circuit.consecutive_failures >= AUTOMATIC_FAILURE_LIMIT:
                self.circuit.open = True
        return CompressionReport(
            trigger,
            "failed",
            before,
            after,
            circuit_open=self.circuit.open,
            message=result.message,
        )

    def record_usage(self, usage: TokenUsage | None, request: PromptRequest) -> None:
        if usage is None or usage.prompt_tokens is None:
            return
        self.estimator.record_usage(usage.prompt_tokens, request.messages, request.tools)

    def unsafe_persistence_failure(
        self,
        conversation: ConversationContext,
        estimated_tokens: int,
    ) -> bool:
        has_failure = any(entry.persistence_failed for entry in conversation.snapshot().entries)
        return has_failure and estimated_tokens >= self.config.forced_threshold
