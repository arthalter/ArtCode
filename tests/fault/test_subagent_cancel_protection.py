from __future__ import annotations

import asyncio
import json
from pathlib import Path

from artcode.agent import NORMAL_AGENT_MODE
from artcode.background import BackgroundTaskManager
from artcode.conversation import ConversationContext
from artcode.permissions import PermissionMode, PermissionState
from artcode.providers.events import content_delta_event, done_event, tool_calls_event
from artcode.providers.tool_calls import ToolCall
from artcode.subagents import RoleCatalog
from artcode.subagents.tool import AgentTool
from artcode.tools import ToolEnvironment, ToolRunContext
from artcode.worktrees import WorktreeManager
from tests.fixtures.git_repositories import init_repository
from tests.fixtures.subagents import make_factory, write_role


class _WriteThenBlockProvider:
    """Stream one: write a file. Stream two: block until released, so the
    cancellation lands while the sub-agent is mid-flight."""

    def __init__(self, write_call: ToolCall) -> None:
        self.write_call = write_call
        self.gate = asyncio.Event()
        self.released = False

    async def stream(self, request):
        if not self.released:
            self.released = True
            yield tool_calls_event([self.write_call])
            yield done_event()
            return
        await self.gate.wait()
        yield content_delta_event("never finishes")
        yield done_event()

    async def close(self) -> None:
        return None


async def test_cancel_keeps_written_files_and_protected_worktree(
    tmp_path: Path,
) -> None:
    """E10: cancelling a running writer sub-agent does not roll back its
    completed file writes; the worktree goes through the same protection
    judgement as a natural finish and is retained."""
    init_repository(tmp_path, files={"main.txt": "original" + chr(10)})
    role_dir = tmp_path / ".artcode" / "agents"
    write_role(
        role_dir / "writer.md",
        name="writer",
        allow=["write_file"],
        isolation="worktree",
        permission_mode="edit",
    )
    provider = _WriteThenBlockProvider(
        ToolCall("w1", "write_file", '{"path":"child.txt","content":"saved before cancel"}')
    )
    tasks = BackgroundTaskManager()
    factory = make_factory(provider=provider, workspace=tmp_path)
    tool = AgentTool(
        RoleCatalog(project_dir=role_dir, user_dir=tmp_path / "u", builtin_dir=tmp_path / "b"),
        factory,
        tasks,
        ConversationContext(),
        foreground_timeout_seconds=0.1,
    )
    state = PermissionState(mode=PermissionMode.EDIT)
    context = ToolRunContext(
        ToolEnvironment.from_workspace(tmp_path), NORMAL_AGENT_MODE, state.snapshot()
    )
    prepared = tool.prepare(
        {"type": "definition", "task": "写入并等待", "role": "writer"}, context
    )
    result = await tool.execute(prepared, context)
    assert result.ok
    task_id = json.loads(result.content)["task_id"]

    # The first tool round executed the write before the second stream
    # started, so the file exists in the worktree at cancel time.
    for _ in range(200):
        detail = tasks.get(task_id)
        if detail is not None and detail.result is not None:
            break
        await asyncio.sleep(0.01)
    assert provider.released

    assert tasks.cancel(task_id) is True
    provider.gate.set()
    await tasks.wait(task_id)
    detail = tasks.get(task_id)

    assert detail is not None and detail.status.value == "cancelled"
    assert detail.result is not None
    # The completed write is not rolled back.
    handoff = detail.result.handoff
    assert handoff is not None and handoff.retained is True
    assert (handoff.path / "child.txt").read_text(encoding="utf-8") == "saved before cancel"
    assert handoff.untracked_changes == 1
    # The main workspace was never touched.
    assert not (tmp_path / "child.txt").exists()
