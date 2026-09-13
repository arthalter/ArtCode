from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from artcode._session import LocalSession
from artcode._tool import LocalTools
from artcode._workspace import LocalWorkspace
from artcode.core.model import Completed, ModelMessage, ModelRequest, ProtocolMetadata, TextDelta, ToolRequest
from artcode.core.session import AssistantCompletion, RunCompletion, RunContribution, SessionSelection
from artcode.core.tool import RunMode, ToolResult


class SummaryModel:
    def __init__(self, text="short summary"):
        self.calls = 0
        self.text = text

    async def stream(self, request):
        self.calls += 1
        yield TextDelta(self.text)
        yield Completed("stop")

    async def close(self):
        pass


def empty_tools(root: Path):
    return replace(LocalTools().open_run(LocalWorkspace(root), RunMode.CHAT), descriptors=())


def append_exchange(session, request, number, *, size=2000):
    calls = (ToolRequest(f"call-{number}", "read_file", '{"path":"sample.py"}'),)
    results = (ToolResult(f"call-{number}", "read_file", True, "x" * size),)
    metadata = ProtocolMetadata(f"opaque-{number}".encode())
    session.commit_tool_exchange(calls, results, metadata=metadata, assistant_text="reading")
    return replace(request, prompt=(*request.prompt, ModelMessage("assistant", "reading", calls, metadata=metadata), ModelMessage("tool", results[0].content, tool_request_id=calls[0].id)))


async def test_active_run_compacts_without_repeating_goal_or_losing_frozen_sources(tmp_path):
    (tmp_path / "ARTCODE.md").write_text("frozen instructions")
    user_home = tmp_path / "home"
    user_home.mkdir()
    (user_home / "memory.md").write_text("- frozen memory\n")
    session = LocalSession(tmp_path, SessionSelection.new(), user_home=user_home, context_window_tokens=1800, recent_fact_count=1)
    run_tools = empty_tools(tmp_path)
    session.commit_user("earlier exact user")
    session.commit_assistant("a" * 6000, AssistantCompletion.NATURAL)
    session.add_notice("frozen notice")
    lease = await session.prepare_run("current exact goal", run_tools, contributions=(RunContribution("review", "frozen skill", "special"),))
    dispatched = session.dispatch_run(lease)
    request = append_exchange(session, dispatched.request, 1, size=700)
    facts = session.snapshot().facts
    (tmp_path / "ARTCODE.md").write_text("changed instructions")
    (user_home / "memory.index.md").write_text("changed memory")
    model = SummaryModel()

    prepared = await session.prepare_next_request(lease, request, run_tools, model=model)

    assert prepared.can_continue and prepared.compaction.status == "success"
    assert prepared.budget.tokens < 1800
    assert session.snapshot().facts == facts
    assert [item.content for item in prepared.request.prompt if item.role == "user"] == ["earlier exact user", "current exact goal"]
    rendered = str(prepared.request)
    for frozen in ("frozen instructions", "frozen memory", "frozen notice", "frozen skill"):
        assert frozen in rendered
    assert "changed memory" not in rendered
    assert prepared.request.model == "special"
    assert prepared.request.prompt[-2:] == request.prompt[-2:]
    assert session.dispatch_run(lease) == dispatched
    session.finish_run(lease, RunCompletion.NATURAL, assistant_text="done")
    session.close()


async def test_fork_keeps_parent_prefix_verbatim_while_compacting_local_exchanges(tmp_path):
    parent = ModelRequest((
        ModelMessage("system", "<summary through=\"999\">parent remains</summary>"),
        ModelMessage("user", "parent user"),
        ModelMessage("assistant", "parent assistant"),
    ), max_output_tokens=99, thinking_enabled=True, model="parent-model")
    session = LocalSession(tmp_path, SessionSelection.new(), context_window_tokens=1200, recent_fact_count=1)
    tools = empty_tools(tmp_path)
    session.add_notice("child notice")
    lease = await session.prepare_run("child goal", tools, frozen_prompt=parent, contributions=(RunContribution("child", "child instructions"),))
    dispatched = session.dispatch_run(lease)
    assert dispatched.request.prompt[:len(parent.prompt)] == parent.prompt
    request = append_exchange(session, dispatched.request, 1, size=5000)
    request = append_exchange(session, request, 2, size=500)
    facts = session.snapshot().facts
    prepared = await session.prepare_next_request(lease, request, tools, model=SummaryModel())
    assert prepared.compaction.status == "success"
    assert prepared.request.prompt[:len(parent.prompt)] == parent.prompt
    assert prepared.request.prompt[-2:] == request.prompt[-2:]
    assert prepared.request.max_output_tokens == 99
    assert prepared.request.thinking_enabled is True
    assert prepared.request.model == "parent-model"
    assert session.snapshot().facts == facts
    assert [item.content for item in prepared.request.prompt if item.role == "user"] == ["parent user", "child goal"]
    session.close()


async def test_oversized_fork_prefix_stops_without_repeated_summarization(tmp_path):
    parent = ModelRequest((ModelMessage("user", "p" * 8000),))
    session = LocalSession(tmp_path, SessionSelection.new(), context_window_tokens=500)
    tools = empty_tools(tmp_path)
    lease = await session.prepare_run("child", tools, frozen_prompt=parent)
    request = session.dispatch_run(lease).request
    model = SummaryModel()
    for _ in range(3):
        prepared = await session.prepare_next_request(lease, request, tools, model=model)
        assert not prepared.can_continue
        assert prepared.request.prompt[:1] == parent.prompt
        request = prepared.request
    assert model.calls == 0
    session.close()


async def test_current_budget_counts_tool_arguments_metadata_and_new_schema(tmp_path):
    from artcode.core.tool import ToolDescriptor, ToolEffect
    session = LocalSession(tmp_path, SessionSelection.new(), context_window_tokens=1000)
    tools = empty_tools(tmp_path)
    lease = await session.prepare_run("goal", tools)
    request = session.dispatch_run(lease).request
    calls = (ToolRequest("large", "tool", '{"input":"' + "a" * 4000 + '"}'),)
    metadata = ProtocolMetadata(b"b" * 4000)
    results = (ToolResult("large", "tool", True, "ok"),)
    session.commit_tool_exchange(calls, results, metadata=metadata)
    request = replace(request, prompt=(*request.prompt, ModelMessage("assistant", None, calls, metadata=metadata), ModelMessage("tool", "ok", tool_request_id="large")))
    newer = replace(tools, descriptors=(ToolDescriptor("new-tool", "new schema", '{"enum":["' + "s" * 4000 + '"]}', ToolEffect.OBSERVE),))
    prepared = await session.prepare_next_request(lease, request, newer, model=SummaryModel())
    assert prepared.budget.tokens >= 3000
    assert not prepared.can_continue
    assert prepared.request.tools[0].name == "new-tool"
    session.close()


async def test_old_cumulative_usage_does_not_exhaust_new_request_budget(tmp_path):
    from artcode.core.model import Usage
    session = LocalSession(tmp_path, SessionSelection.new(), context_window_tokens=1500)
    tools = empty_tools(tmp_path)
    lease = await session.prepare_run("previous", tools)
    session.dispatch_run(lease)
    session.finish_run(lease, RunCompletion.NATURAL, assistant_text="done", usage=Usage(999999))
    lease = await session.prepare_run("current", tools)
    request = session.dispatch_run(lease).request
    prepared = await session.prepare_next_request(lease, request, tools, model=SummaryModel())
    assert prepared.can_continue
    assert prepared.budget.tokens < 1500
    session.close()


async def test_later_session_user_is_not_injected_into_active_prompt(tmp_path):
    session = LocalSession(tmp_path, SessionSelection.new())
    tools = empty_tools(tmp_path)
    lease = await session.prepare_run("original", tools)
    request = session.dispatch_run(lease).request
    session.commit_user("unrelated later run")
    prepared = await session.prepare_next_request(lease, request, tools, model=SummaryModel())
    assert "unrelated later run" not in str(prepared.request)
    session.close()


async def test_recent_provider_usage_calibrates_growth_and_resets_after_compaction(tmp_path):
    from artcode.core.model import Usage
    session = LocalSession(tmp_path, SessionSelection.new(), context_window_tokens=1200, recent_fact_count=1)
    tools = empty_tools(tmp_path)
    lease = await session.prepare_run("goal", tools)
    request = session.dispatch_run(lease).request
    first = await session.prepare_next_request(lease, request, tools, model=SummaryModel())
    request = append_exchange(session, first.request, 1, size=400)
    reported = Usage(800)
    calibrated = await session.prepare_next_request(lease, request, tools, model=SummaryModel(), usage=reported)
    assert 900 <= calibrated.budget.tokens < 1200
    assert calibrated.budget.source == "provider_usage_delta"
    request = append_exchange(session, calibrated.request, 2, size=400)
    model = SummaryModel()
    compacted = await session.prepare_next_request(lease, request, tools, model=model, usage=reported)
    assert compacted.compaction.status == "success"
    assert compacted.budget.tokens < 400
    assert compacted.budget.source == "deterministic_estimate"
    again = await session.prepare_next_request(lease, compacted.request, tools, model=model, usage=reported)
    assert again.budget == compacted.budget
    assert model.calls == 1
    session.close()


async def test_initial_automatic_compaction_preserves_latest_complete_exchange(tmp_path):
    session = LocalSession(tmp_path, SessionSelection.new(), context_window_tokens=1600, recent_fact_count=0)
    tools = empty_tools(tmp_path)
    session.commit_user("previous user")
    session.commit_assistant("history " * 700, AssistantCompletion.NATURAL)
    call = ToolRequest("last", "read_file", "{}")
    metadata = ProtocolMetadata(b"continue-exactly")
    session.commit_tool_exchange((call,), (ToolResult("last", "read_file", True, "latest output"),), metadata=metadata)
    lease = await session.prepare_run("next user", tools, model_for_compaction=SummaryModel())
    assert session.snapshot().summary_active
    exchange = [item for item in lease.prompt_preview.prompt if item.tool_requests]
    assert len(exchange) == 1 and exchange[0].tool_requests == (call,)
    assert exchange[0].metadata == metadata
    assert [item.content for item in lease.prompt_preview.prompt if item.role == "user"] == ["previous user", "next user"]
    session.close()


async def test_completed_historical_exchange_does_not_pin_later_finished_dialogue(tmp_path):
    session = LocalSession(
        tmp_path, SessionSelection.new(), context_window_tokens=1000, recent_fact_count=0,
    )
    tools = empty_tools(tmp_path)
    session.commit_user("old exact user")
    call = ToolRequest("old-completed", "read_file", "{}")
    session.commit_tool_exchange(
        (call,), (ToolResult(call.id, call.name, True, "old output " * 500),),
        metadata=ProtocolMetadata(b"old-completed-metadata"),
    )
    session.commit_assistant("completed tool task", AssistantCompletion.NATURAL)
    for number in range(3):
        session.commit_user(f"finished question {number}")
        session.commit_assistant("finished answer " * 30, AssistantCompletion.NATURAL)
    lease = await session.prepare_run("new exact goal", tools)
    request = session.dispatch_run(lease).request
    facts = session.snapshot().facts

    prepared = await session.prepare_next_request(lease, request, tools, model=SummaryModel())

    assert prepared.can_continue
    assert prepared.compaction.status == "success"
    assert not any(message.tool_requests or message.role == "tool" for message in prepared.request.prompt)
    assert [message.content for message in prepared.request.prompt if message.role == "user"] == [
        "old exact user", "finished question 0", "finished question 1", "finished question 2", "new exact goal",
    ]
    assert session.snapshot().facts == facts
    session.close()
