from __future__ import annotations

from artcode.config import ContextConfig
from artcode.context_management import ContextManager
from artcode.context_management.models import CompressionCircuit, CompressionTrigger
from artcode.context_management.retention import RetentionPlanner
from artcode.context_management.summarizer import SummaryResult
from artcode.conversation import ConversationContext
from artcode.prompting.assembler import PromptRequest
from artcode.agent.events import TokenUsage


class FakeSummarizer:
    def __init__(self, statuses: list[str]) -> None:
        self.statuses = statuses
        self.calls = 0

    async def summarize(self, snapshot, plan):
        self.calls += 1
        status = self.statuses.pop(0)
        return SummaryResult(status, "summary failed" if status == "failed" else "")


def compressible_context(message_size: int = 100) -> ConversationContext:
    context = ConversationContext("system")
    for index in range(12):
        if index % 2 == 0:
            context.append_user(f"u{index}" + "x" * message_size)
        else:
            context.append_assistant(f"a{index}" + "y" * message_size)
    return context


def manager(statuses: list[str], circuit=None) -> ContextManager:
    return ContextManager(
        ContextConfig(),
        FakeSummarizer(statuses),
        retention_planner=RetentionPlanner(recent_token_budget=50, minimum_messages=3),
        circuit=circuit,
    )


def test_trigger_thresholds_and_forced_once_per_cycle() -> None:
    context_manager = manager([])

    assert context_manager.choose_trigger(834_999) is None
    assert context_manager.choose_trigger(835_000) is CompressionTrigger.AUTOMATIC
    assert context_manager.choose_trigger(885_000) is CompressionTrigger.FORCED
    context_manager.circuit.forced_attempted = True
    assert context_manager.choose_trigger(200_000) is None


async def test_three_automatic_failures_open_circuit() -> None:
    context_manager = manager(["failed", "failed", "failed"])
    context = compressible_context()

    reports = [
        await context_manager.compact(context, CompressionTrigger.AUTOMATIC)
        for _ in range(3)
    ]

    assert [report.status for report in reports] == ["failed", "failed", "failed"]
    assert context_manager.circuit.open is True
    assert context_manager.circuit.consecutive_failures == 3
    assert context_manager.choose_trigger(170_000) is None


async def test_forced_failure_is_attempted_once_and_does_not_block_request() -> None:
    circuit = CompressionCircuit(3, True, False)
    context_manager = manager(["failed"], circuit)
    context = compressible_context()

    report = await context_manager.compact(context, CompressionTrigger.FORCED)

    assert report.status == "failed"
    assert context_manager.circuit.forced_attempted is True
    assert context_manager.choose_trigger(190_000) is None


async def test_manual_success_resets_open_circuit() -> None:
    circuit = CompressionCircuit(3, True, True)
    context_manager = manager(["success"], circuit)

    report = await context_manager.compact(compressible_context(), CompressionTrigger.MANUAL)

    assert report.status == "success"
    assert context_manager.circuit == CompressionCircuit()


async def test_manual_short_history_is_noop_without_provider() -> None:
    context_manager = manager(["success"])
    context = ConversationContext("system")
    context.append_user("short")

    report = await context_manager.compact(context, CompressionTrigger.MANUAL)

    assert report.status == "noop"
    assert context_manager.summarizer.calls == 0


def test_record_usage_anchors_only_real_prompt_usage() -> None:
    context_manager = manager([])
    request = PromptRequest([{"role": "user", "content": "hello"}], None)

    context_manager.record_usage(TokenUsage(prompt_tokens=123), request)

    assert context_manager.estimator.anchor.prompt_tokens == 123


def test_persistence_failure_blocks_only_at_forced_safety_line() -> None:
    context_manager = manager([])
    context = compressible_context()
    context.mark_persistence_failed(context.snapshot().entries[-1].id)

    assert context_manager.unsafe_persistence_failure(context, 884_999) is False
    assert context_manager.unsafe_persistence_failure(context, 885_000) is True


async def test_oversized_verbatim_user_message_blocks_without_summarizer_call() -> None:
    context_manager = manager(["success"])
    context = ConversationContext("system")
    context.append_user("中" * 990_001)
    for index in range(10):
        context.append_assistant("recent")

    report = await context_manager.compact(context, CompressionTrigger.MANUAL)

    assert report.status == "blocked"
    assert "开始新会话" in report.message
    assert context_manager.summarizer.calls == 0
