from __future__ import annotations

from pathlib import Path
import asyncio

from artcode._application import LocalApplication
from artcode.core.application import RunStopped, TextOutput
from artcode.core.session import AssistantFact, UserFact
from artcode.core.model import Completed, ModelRequest, TextDelta, ToolRequest, ToolRequests
from tests.application.conftest import FakeModel, options


async def test_normal_run_streams_and_commits_through_single_application_path(tmp_path: Path) -> None:
    model = FakeModel()
    app = await LocalApplication.create(options(tmp_path), model=model)

    events = await app.handle("hello")

    assert any(isinstance(item, TextOutput) and item.text == "reply:hello" for item in events)
    assert isinstance(events[-1], RunStopped) and events[-1].reason == "natural"
    assert [type(item) for item in app.snapshot().session.facts] == [UserFact, AssistantFact]
    await app.close()


async def test_plan_then_act_uses_saved_plan_and_additional_constraints(tmp_path: Path) -> None:
    model = FakeModel()
    app = await LocalApplication.create(options(tmp_path), model=model)

    plan = await app.handle("/plan make a plan")
    act = await app.handle("/act keep tests green")

    assert any(isinstance(item, TextOutput) and item.text == "THE PLAN" for item in plan)
    assert any(isinstance(item, TextOutput) and item.text == "ACTED" for item in act)
    last_user = [item for item in app.snapshot().session.facts if isinstance(item, UserFact)][-1]
    assert "THE PLAN" in last_user.text and "keep tests green" in last_user.text
    await app.close()


async def test_agent_tool_and_completion_notice_use_safe_prompt_boundary(tmp_path: Path) -> None:
    selected = options(tmp_path)
    roles = selected.workspace / ".artcode/agents"
    roles.mkdir(parents=True)
    roles.joinpath("reader.md").write_text(
        "---\nname: reader\ndescription: reader role\ntools:\n  allow: ['read_file']\n  deny: []\n"
        "model: inherit\nmax_rounds: 5\npermission_mode: default\nisolation: none\n---\nROLE-SOP\n",
        encoding="utf-8",
    )

    class RouterModel:
        def __init__(self):
            self.requests = []
            self.closed = 0

        async def stream(self, request: ModelRequest):
            self.requests.append(request)
            system = "\n".join(item.content or "" for item in request.prompt if item.role == "system")
            if "Extract durable memory" in system:
                yield TextDelta('{"user_preferences":[],"project_facts":[]}')
                yield Completed("stop")
                return
            last_user = next(item.content for item in reversed(request.prompt) if item.role == "user")
            if last_user == "delegate" and request.prompt[-1].role != "tool":
                yield ToolRequests((ToolRequest("agent-1", "agent", '{"type":"definition","task":"child task","role":"reader","background":true}'),))
                yield Completed("tool_calls")
            elif last_user == "child task":
                yield TextDelta("child-result")
                yield Completed("stop")
            elif last_user == "delegate":
                yield TextDelta("delegated")
                yield Completed("stop")
            else:
                yield TextDelta("consumed")
                yield Completed("stop")

        async def close(self): self.closed += 1

    model = RouterModel()
    app = await LocalApplication.create(selected, model=model)

    await app.handle("delegate")
    task = app.subagents.list()[0]
    await app.subagents.wait(task.id)
    await app.handle("consume notification")
    notice_requests = [
        request for request in model.requests
        if "<task-notification>" in "\n".join(item.content or "" for item in request.prompt)
    ]

    assert len(notice_requests) == 1
    rendered = "\n".join(item.content or "" for item in notice_requests[0].prompt)
    assert "child-result" in rendered
    assert "ROLE-SOP" not in rendered
    assert app.subagents.take_notifications() == ()
    await app.close()


async def test_stream_interface_delivers_text_before_model_completion(tmp_path: Path) -> None:
    class StreamingModel:
        def __init__(self):
            self.release = asyncio.Event()
        async def stream(self, request):
            yield TextDelta("early")
            await self.release.wait()
            yield Completed("stop")
        async def close(self): pass

    model = StreamingModel()
    app = await LocalApplication.create(options(tmp_path), model=model)
    stream = app.stream("hello")

    first = await asyncio.wait_for(anext(stream), 0.5)
    assert isinstance(first, TextOutput) and first.text == "early"
    model.release.set()
    remaining = [event async for event in stream]
    assert isinstance(remaining[-1], RunStopped)
    await app.close()
