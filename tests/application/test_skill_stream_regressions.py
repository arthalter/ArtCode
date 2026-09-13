from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from artcode._application import LocalApplication
from artcode.core.application import ErrorOutput, RunStopped, StateOutput, TextOutput
from artcode.core.model import Completed, TextDelta
from artcode.core.session import AssistantFact, UserFact
from tests.application.conftest import FakeModel, options


def write_skill(workspace: Path, name: str, mode: str = "shared") -> None:
    directory = workspace / ".artcode" / "skills"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{name}.md").write_text(
        f"---\nname: {name}\ndescription: {name}\ntools: ['read_file']\n"
        f"mode: {mode}\n---\n{name.upper()}-SOP\n",
        encoding="utf-8",
    )


class GatedModel(FakeModel):
    def __init__(self) -> None:
        super().__init__()
        self.release = asyncio.Event()
        self.started = asyncio.Event()

    async def stream(self, request):
        system = "\n".join(item.content or "" for item in request.prompt if item.role == "system")
        if "Extract durable memory" in system:
            async for event in super().stream(request):
                yield event
            return
        self.requests.append(request)
        self.started.set()
        yield TextDelta("first ")
        await self.release.wait()
        yield TextDelta("last")
        yield Completed("stop")


@pytest.mark.parametrize("cancel", [False, True])
async def test_explicit_shared_skill_streams_before_completion_and_supports_cancel(
    tmp_path: Path, cancel: bool
) -> None:
    selected = options(tmp_path)
    write_skill(selected.workspace, "review")
    model = GatedModel()
    app = await LocalApplication.create(selected, model=model)
    stream = app.stream("/skill review inspect this code")
    try:
        first = await asyncio.wait_for(anext(stream), 1)
        assert first == TextOutput("first ", streaming=True)
        assert app.snapshot().running
        rendered = "\n".join(item.content or "" for item in model.requests[0].prompt)
        assert "REVIEW-SOP" in rendered
        assert "inspect this code" in rendered
        if cancel:
            assert app.cancel_current()
        else:
            model.release.set()
        remaining = await asyncio.wait_for(_collect(stream), 1)
        assert remaining[-1] == RunStopped("cancelled" if cancel else "natural", 1)
        assert not app.snapshot().running
        assert not app.cancel_current()
        if not cancel:
            assert TextOutput("last", streaming=True) in remaining
            facts = app.snapshot().session.facts
            assert [type(item) for item in facts] == [UserFact, AssistantFact]
            assert facts[0].text == "inspect this code"
            assert facts[1].text == "first last"
    finally:
        model.release.set()
        await stream.aclose()
        await app.close()


async def _collect(stream):
    return [event async for event in stream]


async def test_explicit_shared_selection_is_not_replaced_by_a_skill_named_in_the_input(
    tmp_path: Path,
) -> None:
    selected = options(tmp_path)
    write_skill(selected.workspace, "review")
    write_skill(selected.workspace, "audit", mode="isolated")
    model = FakeModel()
    app = await LocalApplication.create(selected, model=model)
    try:
        events = await app.handle("/skill review inspect the audit command")

        assert events[-1] == RunStopped("natural", 1)
        rendered = "\n".join(item.content or "" for item in model.requests[0].prompt)
        assert "REVIEW-SOP" in rendered
        assert "AUDIT-SOP" not in rendered
        assert app.snapshot().skills.active == ("review",)
    finally:
        await app.close()


async def test_skill_activation_and_unknown_skill_remain_local_commands(tmp_path: Path) -> None:
    selected = options(tmp_path)
    write_skill(selected.workspace, "review")
    model = FakeModel()
    app = await LocalApplication.create(selected, model=model)
    try:
        activation = await app.handle("/skill review")
        unknown = await app.handle("/skill missing inspect this code")

        assert isinstance(activation[0], StateOutput)
        assert activation[0].name == "skill"
        assert isinstance(unknown[0], ErrorOutput)
        assert model.requests == []
        assert app.snapshot().session.facts == ()
    finally:
        await app.close()


async def test_explicit_isolated_skill_still_returns_summary_and_state(tmp_path: Path) -> None:
    selected = options(tmp_path)
    write_skill(selected.workspace, "audit", mode="isolated")
    model = FakeModel()
    app = await LocalApplication.create(selected, model=model)
    try:
        events = await app.handle("/skill audit inspect this code")

        assert events[0] == TextOutput("reply:inspect this code")
        assert isinstance(events[1], StateOutput)
        assert events[1].name == "isolated_skill"
        assert [type(item) for item in app.snapshot().session.facts] == [UserFact, AssistantFact]
    finally:
        await app.close()


@pytest.mark.parametrize("goal", ["/skill audit inspect this code", "audit this code"])
async def test_isolated_skill_tracks_current_run_and_can_cancel_then_run_again(
    tmp_path: Path, goal: str
) -> None:
    selected = options(tmp_path)
    write_skill(selected.workspace, "audit", mode="isolated")
    model = GatedModel()
    app = await LocalApplication.create(selected, model=model)
    stream = app.stream(goal)
    pending = asyncio.create_task(anext(stream))
    try:
        await asyncio.wait_for(model.started.wait(), 1)
        assert app.snapshot().running
        assert app.cancel_current()
        first = await asyncio.wait_for(pending, 1)
        remaining = await asyncio.wait_for(_collect(stream), 1)

        assert isinstance(first, TextOutput)
        assert remaining[-1].name == "isolated_skill"
        assert remaining[-1].value.stop_reason.value == "cancelled"
        assert not app.snapshot().running
        assert not app.cancel_current()

        model.release.set()
        next_run = await app.handle("hello")
        assert next_run[-1] == RunStopped("natural", 1)
    finally:
        model.release.set()
        if not pending.done():
            pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)
        await stream.aclose()
        await app.close()


@pytest.mark.parametrize("goal", ["/skill audit inspect this code", "audit this code"])
async def test_isolated_skill_exception_resets_running_state_and_returns_an_error(
    tmp_path: Path, goal: str
) -> None:
    class FailsOnceModel(FakeModel):
        failed = False

        async def stream(self, request):
            if not self.failed:
                self.failed = True
                raise RuntimeError("provider temporarily unavailable")
            async for event in super().stream(request):
                yield event

    selected = options(tmp_path)
    write_skill(selected.workspace, "audit", mode="isolated")
    app = await LocalApplication.create(selected, model=FailsOnceModel())
    try:
        assert await app.handle(goal) == (ErrorOutput("provider temporarily unavailable"),)
        assert not app.snapshot().running
        assert not app.cancel_current()
        assert (await app.handle("hello"))[-1] == RunStopped("natural", 1)
    finally:
        await app.close()
