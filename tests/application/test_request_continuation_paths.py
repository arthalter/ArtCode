from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

from artcode._application import LocalApplication
from artcode.core.application import ErrorOutput, StateOutput, TextOutput
from artcode.core.model import Completed, ModelRequest, TextDelta, ToolRequest, ToolRequests, Usage
from artcode.core.session import AssistantCompletion, ToolExchangeFact, UserFact
from artcode.core.subagent import TaskState
from tests.application.conftest import AllowInteraction, options, write_config
from tests.contracts.test_skill_interface import write_skill
from tests.contracts.test_subagent_interface import write_role


GOAL = "inspect all chunks"


class LongRunModel:
    def __init__(self, path: str):
        self.path = path
        self.requests: list[ModelRequest] = []
        self.summaries = 0

    async def stream(self, request: ModelRequest):
        system = "\n".join(item.content or "" for item in request.prompt if item.role == "system")
        if "Extract durable memory" in system:
            yield TextDelta('{"user_preferences":[],"project_facts":[]}')
            yield Completed("stop")
            return
        if "Summarize only" in system:
            self.summaries += 1
            yield TextDelta("The previous chunks were read successfully.")
            yield Completed("stop")
            return
        goal = next(item.content for item in reversed(request.prompt) if item.role == "user")
        if goal == "delegate the inspection":
            if request.prompt[-1].role == "tool":
                yield TextDelta("delegation recorded")
                yield Completed("stop")
            else:
                yield ToolRequests((ToolRequest("delegate", "agent", json.dumps({
                    "type": self.path, "task": GOAL, "role": "reader",
                    "background": self.path == "fork",
                })),))
                yield Completed("tool_calls")
            return
        assert goal == GOAL
        self.requests.append(request)
        round_number = len(self.requests)
        if round_number > 1:
            assert request.prompt[-1].tool_request_id == f"chunk-{round_number - 1}"
            assert "CHUNK-DATA" in request.prompt[-1].content
        if round_number <= 24:
            yield ToolRequests((ToolRequest(f"chunk-{round_number}", "read_file", '{"path":"chunk.txt"}'),))
            yield Completed("tool_calls")
        else:
            yield TextDelta("all chunks inspected")
            yield Completed("stop")

    async def close(self):
        pass


@pytest.mark.parametrize("path", ["normal", "shared", "isolated", "definition", "fork"])
async def test_long_tool_run_compacts_through_every_execution_path(tmp_path: Path, path: str) -> None:
    selected = options(tmp_path)
    write_config(selected.config_path, context={"window_tokens": 10_000})
    (selected.workspace / "chunk.txt").write_text("CHUNK-DATA " * 250)
    if path in {"shared", "isolated"}:
        write_skill(selected.workspace / ".artcode/skills", "reader", mode=path, sop="KEEP-THIS-SOP")
    if path in {"definition", "fork"}:
        write_role(selected.workspace / ".artcode/agents", "reader", max_rounds=30, sop="KEEP-THIS-SOP")
    model = LongRunModel(path)
    app = await LocalApplication.create(selected, model=model)
    try:
        command = (
            f"/skill reader {GOAL}" if path in {"shared", "isolated"}
            else "delegate the inspection" if path in {"definition", "fork"}
            else GOAL
        )
        events = await app.handle(command)
        assert not [event for event in events if isinstance(event, ErrorOutput)]
        if path in {"definition", "fork"}:
            tasks = app.subagents.list()
            assert len(tasks) == 1
            finished = await app.subagents.wait(tasks[0].id)
            assert finished.state is TaskState.COMPLETED, finished.result
            assert finished.result == "all chunks inspected"
            assert finished.rounds == 25
        else:
            assert "all chunks inspected" in "".join(event.text for event in events if isinstance(event, TextOutput))
        assert len(model.requests) == 25
        assert model.summaries >= 1
        first = model.requests[0]
        users = [item for item in first.prompt if item.role == "user"]
        static = [item for item in first.prompt if item.role == "system"]
        for request in model.requests:
            assert [item for item in request.prompt if item.role == "user"] == users
            assert all(item in request.prompt for item in static)
            assert request.tools == first.tools
            assert (request.model, request.thinking_enabled) == (first.model, first.thinking_enabled)
        sizes = [sum(len(item.content or "") for item in request.prompt) for request in model.requests]
        assert any(after < before for before, after in zip(sizes, sizes[1:]))
        if path != "normal":
            assert any("KEEP-THIS-SOP" in (item.content or "") for item in first.prompt)
        facts = app.session.snapshot().facts
        if path in {"normal", "shared", "isolated"}:
            assert [fact.text for fact in facts if isinstance(fact, UserFact)] == [GOAL]
            exchanges = [fact for fact in facts if isinstance(fact, ToolExchangeFact)]
            assert len(exchanges) == (0 if path == "isolated" else 24)
    finally:
        await app.close()


class SearchAndCompactModel:
    def __init__(self):
        self.requests: list[ModelRequest] = []
        self.summaries = 0

    async def stream(self, request: ModelRequest):
        system = "\n".join(item.content or "" for item in request.prompt if item.role == "system")
        if "Extract durable memory" in system:
            yield TextDelta('{"user_preferences":[],"project_facts":[]}')
            yield Completed("stop")
            return
        if "Summarize only" in system:
            self.summaries += 1
            yield TextDelta("Earlier work is complete.")
            yield Completed("stop")
            return
        self.requests.append(request)
        names = {item.name for item in request.tools}
        if len(self.requests) == 1:
            assert "mcp_search_tools" in names and "mcp__local__echo" not in names
            yield ToolRequests((ToolRequest("discover", "mcp_search_tools", '{"query":"provided text"}'),))
            # A real Provider's input measurement can exceed the local estimate.
            # The next request must account for both the result and newly active Schema.
            yield Usage(50_099, 1, 50_100)
            yield Completed("tool_calls")
        elif len(self.requests) == 2:
            assert self.summaries == 1
            assert any("<summary " in (item.content or "") for item in request.prompt)
            assert "mcp__local__echo" in names
            assert request.prompt[-1].tool_request_id == "discover"
            assert json.loads(request.prompt[-1].content)["tools"][0]["active"] is True
            yield ToolRequests((ToolRequest("echo", "mcp__local__echo", '{"text":"after compaction"}'),))
            yield Completed("tool_calls")
        else:
            assert request.prompt[-1].tool_request_id == "echo"
            assert "echo:after compaction" in request.prompt[-1].content
            yield TextDelta("MCP completed after compaction")
            yield Completed("stop")

    async def close(self):
        pass


@pytest.mark.parametrize("shared", [False, True])
async def test_mcp_activation_and_compaction_share_the_next_request(tmp_path: Path, shared: bool) -> None:
    selected = options(tmp_path)
    fixture = Path(__file__).parents[1] / "integration/fixtures/mcp_test_server.py"
    write_config(
        selected.config_path, context={"window_tokens": 60_000}, mcp={"loading": "lazy"},
        mcp_servers={"local": {"transport": "stdio", "command": sys.executable, "args": [str(fixture)]}},
    )
    if shared:
        write_skill(
            selected.workspace / ".artcode/skills", "remote",
            tools=("mcp_search_tools", "mcp__local__echo"), sop="REMOTE-SOP", model="test-model",
        )
    model = SearchAndCompactModel()
    app = await LocalApplication.create(selected, model=model, interaction=AllowInteraction())
    try:
        for index in range(10):
            app.session.commit_user(f"earlier requirement {index}")
            app.session.commit_assistant("historical detail " * 150, AssistantCompletion.NATURAL)
        app.session.add_notice("KEEP-THIS-NOTICE")
        events = await app.handle("/skill remote use the remote echo" if shared else "use the remote echo")
        assert not [event for event in events if isinstance(event, ErrorOutput)]
        assert "MCP completed after compaction" in "".join(event.text for event in events if isinstance(event, TextOutput))
        assert len(model.requests) == 3 and model.summaries == 1
        reports = [event.value for event in events if isinstance(event, StateOutput) and event.name == "compaction"]
        assert len(reports) == 1 and reports[0].status == "success"
        users = [item for item in model.requests[0].prompt if item.role == "user"]
        for request in model.requests:
            assert [item for item in request.prompt if item.role == "user"] == users
            assert sum("KEEP-THIS-NOTICE" in (item.content or "") for item in request.prompt) == 1
            if shared:
                assert any("REMOTE-SOP" in (item.content or "") for item in request.prompt)
                assert request.model == "test-model"
                assert {item.name for item in request.tools} <= {"mcp_search_tools", "mcp__local__echo"}
        exchanges = [fact for fact in app.session.snapshot().facts if isinstance(fact, ToolExchangeFact)]
        assert [fact.requests[0].id for fact in exchanges] == ["discover", "echo"]
        assert all(result.ok for fact in exchanges for result in fact.results)
    finally:
        await app.close()
