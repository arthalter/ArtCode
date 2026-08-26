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


class _WriteThenStallProvider:
    """Writes one file on the first stream, then stalls forever so the
    foreground window expires while the task is still running."""

    def __init__(self) -> None:
        self.gate = asyncio.Event()
        self.first = True

    async def stream(self, request):
        if self.first:
            self.first = False
            yield tool_calls_event([ToolCall("w", "write_file", '{"path":"out.txt","content":"成果"}')])
            yield done_event()
            return
        await self.gate.wait()
        yield content_delta_event("never")
        yield done_event()

    async def close(self) -> None:
        return None


async def test_auto_background_then_cancel_keeps_worktree_across_restart(
    tmp_path: Path,
) -> None:
    """E2E-03: a writing definition task that exceeds the foreground
    window auto-promotes to background, is then cancelled, its worktree is
    retained because of the uncommitted result, a restart scan does not
    delete it, and the user can still locate the result from task details."""
    init_repository(tmp_path, files={"main.txt": "original" + chr(10)})
    role_dir = tmp_path / ".artcode" / "agents"
    write_role(
        role_dir / "writer.md",
        name="writer",
        allow=["write_file"],
        isolation="worktree",
        permission_mode="edit",
    )
    provider = _WriteThenStallProvider()
    tasks = BackgroundTaskManager()
    factory = make_factory(provider=provider, workspace=tmp_path)
    tool = AgentTool(
        RoleCatalog(project_dir=role_dir, user_dir=tmp_path / "u", builtin_dir=tmp_path / "b"),
        factory,
        tasks,
        ConversationContext(),
        # 0.05 s stands in for the production 120 s foreground window (E04).
        foreground_timeout_seconds=0.05,
    )
    state = PermissionState(mode=PermissionMode.EDIT)
    context = ToolRunContext(
        ToolEnvironment.from_workspace(tmp_path), NORMAL_AGENT_MODE, state.snapshot()
    )
    prepared = tool.prepare(
        {"type": "definition", "task": "写成果文件", "role": "writer"}, context
    )

    # The foreground window expires: the tool returns the task id and the
    # task keeps running in the background with the same identity.
    result = await tool.execute(prepared, context)
    assert result.ok
    payload = json.loads(result.content)
    assert payload["background"] is True
    assert payload["status"] in {"queued", "running"}
    task_id = payload["task_id"]

    # Wait until the write executed, then cancel the running task.
    for _ in range(200):
        detail = tasks.get(task_id)
        if detail is not None and detail.result is not None:
            break
        await asyncio.sleep(0.01)
    assert not provider.first
    assert tasks.cancel(task_id) is True
    provider.gate.set()
    detail = await tasks.wait(task_id)

    assert detail is not None and detail.status.value == "cancelled"
    assert detail.result is not None
    handoff = detail.result.handoff
    assert handoff is not None and handoff.retained is True
    worktree_path = handoff.path
    assert (worktree_path / "out.txt").read_text(encoding="utf-8") == "成果"

    # "Restart": a fresh manager's expiry scan keeps the retained worktree.
    manager_restarted = WorktreeManager(tmp_path)
    removed = manager_restarted.cleanup_expired([], max_age_seconds=24 * 3600)
    assert removed == ()
    assert worktree_path.exists()

    # The user can still locate the result from the task details.
    found = manager_restarted.find(task_id)
    assert found is not None and found.path == worktree_path
    assert (found.path / "out.txt").read_text(encoding="utf-8") == "成果"
    # The main workspace stayed untouched.
    assert not (tmp_path / "out.txt").exists()
