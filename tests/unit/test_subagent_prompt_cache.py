from __future__ import annotations

from artcode.agent import NORMAL_AGENT_MODE, RequestPreparer
from artcode.config import ContextConfig
from artcode.context_management import ContextManager
from artcode.context_management.retention import RetentionPlanner
from artcode.context_management.summarizer import SummaryResult
from artcode.conversation import ConversationContext
from artcode.permissions import PermissionState
from artcode.prompting.assembler import PromptRequestAssembler
from artcode.tools import ToolEnvironment, ToolRegistry


class _FixedEstimator:
    def __init__(self, tokens: int) -> None:
        self.tokens = tokens

    def estimate_request(self, _messages, _tools) -> int:
        return self.tokens

    def record_usage(self, *_args) -> None:
        return None


class _FailingSummarizer:
    def __init__(self) -> None:
        self.calls = 0

    async def summarize(self, _snapshot, _plan) -> SummaryResult:
        self.calls += 1
        return SummaryResult("failed", "fixture failure")


def _conversation() -> ConversationContext:
    conversation = ConversationContext("parent-system")
    for index in range(8):
        conversation.append_user(f"user-{index}")
        conversation.append_assistant(f"assistant-{index}")
    return conversation


async def _prepare(tmp_path, estimated: int):
    conversation = _conversation()
    summarizer = _FailingSummarizer()
    manager = ContextManager(
        ContextConfig(200_000),
        summarizer,
        estimator=_FixedEstimator(estimated),
        retention_planner=RetentionPlanner(
            recent_token_budget=1, minimum_messages=1
        ),
    )
    preparer = RequestPreparer(
        conversation,
        PromptRequestAssembler(),
        ToolRegistry(),
        ToolEnvironment.from_workspace(tmp_path),
        PermissionState(),
        context_manager=manager,
        preserve_initial_prefix=True,
    )
    prepared = await preparer.prepare(NORMAL_AGENT_MODE)
    return preparer, prepared, summarizer


async def test_fork_first_request_skips_automatic_compaction(tmp_path) -> None:
    # 170k is above the 167k automatic line but below the 177k forced line.
    preparer, prepared, summarizer = await _prepare(tmp_path, 170_000)

    assert prepared.request is not None
    assert summarizer.calls == 0
    assert prepared.cache_prefix_preserved is True
    preparer.mark_dispatched(prepared)
    assert preparer.initial_cache_prefix_preserved is True


async def test_fork_first_request_marks_forced_compaction_prefix_change(tmp_path) -> None:
    preparer, prepared, summarizer = await _prepare(tmp_path, 180_000)

    assert prepared.request is not None
    assert summarizer.calls == 1
    assert prepared.cache_prefix_preserved is False
    preparer.mark_dispatched(prepared)
    assert preparer.initial_cache_prefix_preserved is False
