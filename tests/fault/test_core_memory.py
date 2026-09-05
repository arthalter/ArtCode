from __future__ import annotations

import asyncio
from pathlib import Path

from artcode._session import LocalSession
from artcode._tool import LocalTools
from artcode._workspace import LocalWorkspace
from artcode.core.model import Completed, ModelRequest, ProtocolFailure, TextDelta
from artcode.core.session import RunCompletion, SessionSelection
from artcode.core.tool import RunMode


class MemoryModel:
    def __init__(self, replies: list[str | Exception]) -> None:
        self.replies = replies
        self.active = 0
        self.max_active = 0

    async def stream(self, request: ModelRequest):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(0)
            reply = self.replies.pop(0)
            if isinstance(reply, Exception):
                raise reply
            yield TextDelta(reply)
            yield Completed("stop")
        finally:
            self.active -= 1

    async def close(self):
        return None


async def test_only_natural_runs_schedule_serial_memory_updates(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    home = tmp_path / "home"
    root.mkdir()
    workspace = LocalWorkspace(root)
    tools = LocalTools()
    session = LocalSession(root, SessionSelection.new(), user_home=home)
    lease = await session.prepare_run("goal", tools.open_run(workspace, RunMode.CHAT))
    model = MemoryModel([
        '{"user_preferences":["concise"],"project_facts":["uses python"]}',
        '{"user_preferences":["tests first"],"project_facts":[]}',
    ])

    assert session.schedule_memory_update(lease, RunCompletion.CANCELLED, "ignored", model) is False
    assert session.schedule_memory_update(lease, RunCompletion.NATURAL, "one", model) is True
    assert session.schedule_memory_update(lease, RunCompletion.NATURAL, "two", model) is True
    await session.wait_memory_idle()

    assert model.max_active == 1
    assert "concise" in (home / "memory.md").read_text(encoding="utf-8")
    assert "tests first" in (home / "memory.md").read_text(encoding="utf-8")
    assert "uses python" in (root / ".artcode/ch14/memory.md").read_text(encoding="utf-8")
    assert "concise" in (home / "memory.index.md").read_text(encoding="utf-8")
    assert "uses python" in (root / ".artcode/ch14/memory.index.md").read_text(encoding="utf-8")
    session.close()


async def test_memory_failure_isolated_and_later_update_still_runs(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    workspace = LocalWorkspace(root)
    tools = LocalTools()
    session = LocalSession(root, SessionSelection.new())
    lease = await session.prepare_run("goal", tools.open_run(workspace, RunMode.CHAT))
    model = MemoryModel([
        ProtocolFailure("injected memory failure"),
        '{"user_preferences":[],"project_facts":["recovered"]}',
    ])
    session.schedule_memory_update(lease, RunCompletion.NATURAL, "one", model)
    session.schedule_memory_update(lease, RunCompletion.NATURAL, "two", model)

    await session.wait_memory_idle()

    assert session.snapshot().last_memory_report.status == "success"
    assert "recovered" in (root / ".artcode/ch14/memory.md").read_text(encoding="utf-8")
    assert session.snapshot().facts[-1].text == "goal"
    session.close()
