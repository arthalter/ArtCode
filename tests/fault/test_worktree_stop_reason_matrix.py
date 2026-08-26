from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from artcode.agent import NORMAL_AGENT_MODE
from artcode.background import BackgroundTaskManager
from artcode.conversation import ConversationContext
from artcode.permissions import PermissionMode, PermissionState
from artcode.providers.events import content_delta_event, done_event, tool_calls_event
from artcode.providers.tool_calls import ToolCall
from artcode.subagents import RoleCatalog
from artcode.subagents.tool import AgentTool
from artcode.tools import ToolEnvironment, ToolRunContext
from tests.fixtures.git_repositories import init_repository
from tests.fixtures.subagents import make_factory, write_role


class _BlockingTail:
    """A provider whose final stream blocks until released."""

    def __init__(self, streams) -> None:
        self.streams = list(streams)
        self.gate = asyncio.Event()

    async def stream(self, request):
        if not self.streams:
            await self.gate.wait()
            yield content_delta_event("blocked")
            yield done_event()
            return
        for event in self.streams.pop(0):
            if isinstance(event, BaseException):
                raise event
            yield event

    async def close(self) -> None:
        return None


WRITE = ToolCall("w", "write_file", '{"path":"child.txt","content":"written"}')
READ = ToolCall("r", "read_file", '{"path":"main.txt"}')


def _streams(reason: str, dirty: bool):
    first_write = (tool_calls_event([WRITE]), done_event()) if dirty else None
    if reason == "natural":
        if dirty:
            return [(tool_calls_event([WRITE]), done_event()), (content_delta_event("done"), done_event())]
        return [(content_delta_event("done"), done_event())]
    if reason == "max_rounds":
        first = (tool_calls_event([WRITE]), done_event()) if dirty else (tool_calls_event([READ]), done_event())
        return [first, (tool_calls_event([READ]), done_event()), (content_delta_event("summary"), done_event())]
    if reason == "provider_error":
        if dirty:
            return [(tool_calls_event([WRITE]), done_event()), (RuntimeError("boom"),)]
        return [(RuntimeError("boom"),)]
    if reason == "cancelled":
        return [(tool_calls_event([WRITE]), done_event())] if dirty else []
    raise AssertionError(reason)


@pytest.mark.parametrize(
    "reason",
    ["natural", "max_rounds", "provider_error", "cancelled"],
)
@pytest.mark.parametrize("dirty", [False, True], ids=("clean", "dirty"))
async def test_all_stop_reasons_share_worktree_protection(
    tmp_path: Path, reason: str, dirty: bool
) -> None:
    """G06: natural finish, round cap, provider error and cancellation all
    run the same handoff protection: dirty worktrees are retained, clean
    ones are removed."""
    init_repository(tmp_path, files={"main.txt": "original" + chr(10)})
    role_dir = tmp_path / ".artcode" / "agents"
    write_role(
        role_dir / "worker.md",
        name="worker",
        allow=["read_file", "write_file"],
        isolation="worktree",
        permission_mode="edit",
        max_rounds=2,
    )
    provider = _BlockingTail(_streams(reason, dirty))
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
        {"type": "definition", "task": "矩阵任务", "role": "worker"}, context
    )
    result = await tool.execute(prepared, context)
    # A provider failure surfaces as a failed tool result; the other reasons
    # return success with the task detail payload. Both carry the task id.
    assert result.ok is (reason != "provider_error"), result.message
    task_id = json.loads(result.content)["task_id"]
    if reason == "cancelled":
        for _ in range(200):
            if provider.streams == [] and tasks.get(task_id) is not None:
                break
            await asyncio.sleep(0.01)
        assert tasks.cancel(task_id) is True
    provider.gate.set()
    detail = await tasks.wait(task_id)

    assert detail is not None and detail.result is not None
    expected_stop = {
        "natural": "natural",
        "max_rounds": "max_rounds",
        "provider_error": "failed",
        "cancelled": "cancelled",
    }[reason]
    assert detail.result.stop_reason.value == expected_stop
    handoff = detail.result.handoff
    assert handoff is not None
    # The protection judgement depends only on the worktree content state.
    assert handoff.retained is dirty
    assert handoff.path.exists() is dirty
    if dirty:
        assert (handoff.path / "child.txt").read_text(encoding="utf-8") == "written"
    assert not (tmp_path / "child.txt").exists()
