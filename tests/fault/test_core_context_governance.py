from __future__ import annotations

from pathlib import Path

from artcode._session import LocalSession
from artcode.core.model import Completed, ModelRequest, ProtocolFailure, TextDelta, ToolRequest, ToolRequests
from artcode.core.session import AssistantCompletion, CompactionTrigger, SessionSelection


class FailingModel:
    def __init__(self) -> None:
        self.calls = 0

    async def stream(self, request: ModelRequest):
        self.calls += 1
        raise ProtocolFailure("injected")
        yield  # pragma: no cover

    async def close(self):
        return None


class InvalidSummaryModel:
    def __init__(self) -> None:
        self.calls = 0

    async def stream(self, request: ModelRequest):
        self.calls += 1
        yield ToolRequests((ToolRequest("x", "forbidden", "{}"),))
        yield Completed("tool_calls")

    async def close(self):
        return None


class SummaryModel:
    def __init__(self) -> None:
        self.calls = 0

    async def stream(self, request: ModelRequest):
        self.calls += 1
        yield TextDelta("bounded summary")
        yield Completed("stop")

    async def close(self):
        return None


async def test_compaction_failure_keeps_transcript_and_previous_summary_unchanged(tmp_path: Path) -> None:
    session = LocalSession(tmp_path, SessionSelection.new(), recent_fact_count=1)
    for index in range(6):
        session.commit_user(f"u{index}")
        session.commit_assistant(f"a{index}", AssistantCompletion.NATURAL)
    before = session.snapshot()
    model = FailingModel()

    first = await session.compact(model, CompactionTrigger.AUTOMATIC)
    second = await session.compact(model, CompactionTrigger.EMERGENCY)

    assert first.status == second.status == "failed"
    assert model.calls == 2
    assert session.snapshot().facts == before.facts
    assert session.snapshot().summary_active is False
    session.close()


async def test_summary_with_tool_request_is_rejected_without_protocol_damage(tmp_path: Path) -> None:
    session = LocalSession(tmp_path, SessionSelection.new(), recent_fact_count=1)
    for index in range(3):
        session.commit_user(f"u{index}")
        session.commit_assistant(f"a{index}", AssistantCompletion.NATURAL)

    report = await session.compact(InvalidSummaryModel(), CompactionTrigger.FORCED)

    assert report.status == "failed"
    assert session.snapshot().summary_active is False
    assert len(session.snapshot().facts) == 6
    session.close()


def test_instruction_cycle_and_outside_include_are_bounded_and_observable(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("outside-secret", encoding="utf-8")
    first = root / "ARTCODE.md"
    second = root / "nested.md"
    first.write_text("root\n@include nested.md\n@include ../outside.md\n", encoding="utf-8")
    second.write_text("nested\n@include ARTCODE.md\n", encoding="utf-8")

    session = LocalSession(root, SessionSelection.new())

    assert any("循环" in issue or "越界" in issue for issue in session.instruction_issues)
    assert "outside-secret" not in session.instruction_text
    session.close()


async def test_automatic_compaction_is_single_attempt_and_repeated_manual_call_is_bounded(tmp_path: Path) -> None:
    from artcode._tool import LocalTools
    from artcode._workspace import LocalWorkspace
    from artcode.core.tool import RunMode

    session = LocalSession(
        tmp_path,
        SessionSelection.new(),
        context_window_tokens=1,
        recent_fact_count=1,
    )
    session.commit_user("old user")
    session.commit_assistant("old assistant", AssistantCompletion.NATURAL)
    model = SummaryModel()

    lease = await session.prepare_run(
        "current",
        LocalTools().open_run(LocalWorkspace(tmp_path), RunMode.CHAT),
        model_for_compaction=model,
    )
    repeated = await session.compact(model, CompactionTrigger.MANUAL)

    assert model.calls == 1
    assert session.snapshot().summary_active is True
    assert repeated.status == "noop"
    assert lease.budget.source == "deterministic_estimate"
    session.close()


async def test_repeated_compaction_includes_previous_summary_in_next_derivation(tmp_path: Path) -> None:
    class RecordingSummaryModel(SummaryModel):
        def __init__(self):
            super().__init__()
            self.requests = []
        async def stream(self, request):
            self.requests.append(request)
            yield TextDelta(f"summary-{self.calls}")
            self.calls += 1
            yield Completed("stop")

    session = LocalSession(tmp_path, SessionSelection.new(), recent_fact_count=0)
    session.commit_user("u1")
    session.commit_assistant("a1", AssistantCompletion.NATURAL)
    model = RecordingSummaryModel()
    assert (await session.compact(model, CompactionTrigger.MANUAL)).status == "success"
    session.commit_user("u2")
    session.commit_assistant("a2", AssistantCompletion.NATURAL)
    assert (await session.compact(model, CompactionTrigger.MANUAL)).status == "success"

    second_input = model.requests[1].prompt[-1].content or ""
    assert "summary-0" in second_input
    assert session.snapshot().summary_active is True
    session.close()
