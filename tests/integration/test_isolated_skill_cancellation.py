from __future__ import annotations

import asyncio
from pathlib import Path
import tempfile

import pytest

from artcode._session import LocalSession
from artcode._skill import LocalSkills
from artcode._tool import LocalTools
from artcode._workspace import LocalWorkspace
from artcode.core.agent import RunControl, RunFinished, StopReason
from artcode.core.model import TextDelta
from artcode.core.session import AssistantFact, SessionSelection, UserFact
from tests.contracts.test_skill_interface import write_skill


class WaitingModel:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.stream_closed = asyncio.Event()

    async def stream(self, request):
        try:
            yield TextDelta("private partial response")
            self.started.set()
            await self.release.wait()
            raise RuntimeError("model execution failed")
        finally:
            self.stream_closed.set()

    async def close(self):
        pass


@pytest.mark.parametrize("cancel", (True, False))
async def test_isolated_run_closes_stream_and_temporary_storage_on_interruption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cancel: bool
) -> None:
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    root = tmp_path / "workspace"
    root.mkdir()
    write_skill(root / ".artcode/skills", "inspect", mode="isolated", history_turns=0)
    workspace = LocalWorkspace(root)
    tools = LocalTools()
    parent = LocalSession(root, SessionSelection.new(), user_home=tmp_path / "home")
    skills = LocalSkills(
        root / ".artcode/skills", tmp_path / "user", tmp_path / "builtin",
        known_tools=lambda: {"read_file"},
    )
    skills.activate("inspect")
    model = WaitingModel()
    control = RunControl()
    execution = asyncio.create_task(
        skills.run_isolated(
            "inspect", "inspect files", parent=parent, workspace=workspace,
            model=model, tools=tools, control=control,
        )
    )
    try:
        await asyncio.wait_for(model.started.wait(), 1)
        assert list(tmp_path.glob("artcode-isolated-skill-*"))
        if cancel:
            control.cancel()
            result = await asyncio.wait_for(execution, 1)
            assert result.stop_reason is StopReason.CANCELLED
            assert isinstance(result.events[-1], RunFinished)
            assert "private partial response" not in result.summary
            assert isinstance(parent.snapshot().facts[-1], AssistantFact)
        else:
            model.release.set()
            with pytest.raises(RuntimeError, match="model execution failed"):
                await asyncio.wait_for(execution, 1)
            assert parent.snapshot().facts == (UserFact("inspect files"),)
        assert model.stream_closed.is_set()
        assert not list(tmp_path.glob("artcode-isolated-skill-*"))
        assert "private partial response" not in repr(parent.snapshot().facts)
    finally:
        if not execution.done():
            execution.cancel()
        await asyncio.gather(execution, return_exceptions=True)
        await parent.aclose()
        await tools.close()
        await workspace.aclose()
