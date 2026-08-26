from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from artcode.agent import NORMAL_AGENT_MODE
from artcode.background import BackgroundTaskManager
from artcode.config import ContextConfig
from artcode.conversation import ConversationContext
from artcode.permissions import PermissionState
from artcode.providers.events import content_delta_event, done_event
from artcode.subagents import AgentCreateRequest, AgentKind, RoleCatalog
from artcode.subagents.factory import SubagentFactory
from artcode.subagents.runner import RunToCompletion
from artcode.subagents.tool import AgentTool
from artcode.tools import ToolEnvironment, ToolRunContext, create_default_tool_registry
from artcode.worktrees import WorktreeManager
from tests.fixtures.providers import ScriptedProvider
from tests.fixtures.subagents import make_factory, write_role


async def test_provider_stream_failure_marks_task_failed_and_keeps_result(
    tmp_path: Path,
) -> None:
    role_dir = tmp_path / ".artcode" / "agents"
    write_role(role_dir / "reader.md", name="reader", allow=["read_file"])
    provider = ScriptedProvider.from_streams(
        ((RuntimeError("simulated provider outage"),),)
    )
    tasks = BackgroundTaskManager()
    factory = make_factory(provider=provider, workspace=tmp_path)
    tool = AgentTool(
        RoleCatalog(project_dir=role_dir, user_dir=tmp_path / "u", builtin_dir=tmp_path / "b"),
        factory,
        tasks,
        ConversationContext(),
    )
    context = ToolRunContext(
        ToolEnvironment.from_workspace(tmp_path), NORMAL_AGENT_MODE, PermissionState().snapshot()
    )
    prepared = tool.prepare({"type": "definition", "task": "失败任务", "role": "reader"}, context)
    result = await tool.execute(prepared, context)

    assert not result.ok
    detail = tasks.get(__import__("json").loads(result.content)["task_id"])
    assert detail is not None and detail.status.value == "failed"
    assert detail.result is not None and detail.result.stop_reason.value == "failed"
    assert "流式响应出错" in detail.error_message


async def test_provider_failure_does_not_disturb_parallel_task(
    tmp_path: Path,
) -> None:
    """Failure isolation: one broken stream leaves another task untouched."""
    role_dir = tmp_path / ".artcode" / "agents"
    write_role(role_dir / "reader.md", name="reader", allow=["read_file"])
    provider = ScriptedProvider.from_streams(
        (
            (RuntimeError("boom"),),
            (content_delta_event("healthy"), done_event()),
        )
    )
    tasks = BackgroundTaskManager()
    factory = make_factory(provider=provider, workspace=tmp_path)
    tool = AgentTool(
        RoleCatalog(project_dir=role_dir, user_dir=tmp_path / "u", builtin_dir=tmp_path / "b"),
        factory,
        tasks,
        ConversationContext(),
    )
    context = ToolRunContext(
        ToolEnvironment.from_workspace(tmp_path), NORMAL_AGENT_MODE, PermissionState().snapshot()
    )

    failed_prepared = tool.prepare({"type": "fork", "task": "坏任务", "role": "reader"}, context)
    healthy_prepared = tool.prepare({"type": "fork", "task": "好任务", "role": "reader"}, context)
    failed_summary = await tool.execute(failed_prepared, context)
    healthy_summary = await tool.execute(healthy_prepared, context)
    await tasks.wait_all()

    failed_id = __import__("json").loads(failed_summary.content)["task_id"]
    healthy_id = __import__("json").loads(healthy_summary.content)["task_id"]
    assert tasks.get(failed_id).status.value == "failed"
    assert tasks.get(healthy_id).status.value == "completed"
    assert "healthy" in tasks.get(healthy_id).result.final_text


class _BlockingProvider:
    """A provider that stalls the model stream until released."""

    def __init__(self) -> None:
        self.gate = asyncio.Event()
        self.requests: list[object] = []
        self.close_count = 0

    async def stream(self, request: object):
        self.requests.append(request)
        await self.gate.wait()
        yield content_delta_event("never")

    async def close(self) -> None:
        self.close_count += 1


async def test_cancelled_subagent_reports_cancelled_stop_reason(
    tmp_path: Path,
) -> None:
    role_dir = tmp_path / ".artcode" / "agents"
    write_role(role_dir / "reader.md", name="reader", allow=["read_file"])
    provider = _BlockingProvider()
    tasks = BackgroundTaskManager()
    factory = make_factory(provider=provider, workspace=tmp_path)
    tool = AgentTool(
        RoleCatalog(project_dir=role_dir, user_dir=tmp_path / "u", builtin_dir=tmp_path / "b"),
        factory,
        tasks,
        ConversationContext(),
    )
    context = ToolRunContext(
        ToolEnvironment.from_workspace(tmp_path), NORMAL_AGENT_MODE, PermissionState().snapshot()
    )
    prepared = tool.prepare({"type": "fork", "task": "取消任务", "role": "reader"}, context)
    summary = await tool.execute(prepared, context)
    task_id = __import__("json").loads(summary.content)["task_id"]
    # Wait until the model stream actually started before cancelling, so the
    # cancellation lands inside the runner instead of during task setup.
    for _ in range(500):
        if provider.requests:
            break
        await asyncio.sleep(0.005)
    assert provider.requests, "sub-agent never reached the model stream"
    assert tasks.cancel(task_id) is True
    await tasks.wait(task_id)

    detail = tasks.get(task_id)
    assert detail is not None and detail.status.value == "cancelled"
    assert detail.result is not None
    assert detail.result.stop_reason.value == "cancelled"


async def test_failed_worktree_creation_never_falls_back_to_main_workspace(
    tmp_path: Path,
) -> None:
    """F33: a non-git workspace fails the task instead of running unisolated."""
    role_dir = tmp_path / ".artcode" / "agents"
    write_role(role_dir / "writer.md", name="writer", allow=["write_file"], isolation="worktree", permission_mode="edit")
    provider = ScriptedProvider.from_streams(
        ((content_delta_event("should not run"), done_event()),)
    )
    tasks = BackgroundTaskManager()
    factory = make_factory(provider=provider, workspace=tmp_path)
    tool = AgentTool(
        RoleCatalog(project_dir=role_dir, user_dir=tmp_path / "u", builtin_dir=tmp_path / "b"),
        factory,
        tasks,
        ConversationContext(),
    )
    context = ToolRunContext(
        ToolEnvironment.from_workspace(tmp_path), NORMAL_AGENT_MODE, PermissionState().snapshot()
    )
    prepared = tool.prepare({"type": "definition", "task": "写文件", "role": "writer"}, context)
    result = await tool.execute(prepared, context)

    assert not result.ok
    assert provider.requests == []
    assert not (tmp_path / "untracked.txt").exists()


async def test_role_refresh_does_not_change_running_task_snapshot(
    tmp_path: Path,
) -> None:
    """F8: already-queued tasks keep the catalog snapshot from their launch."""
    role_dir = tmp_path / ".artcode" / "agents"
    write_role(role_dir / "reader.md", name="reader", allow=["read_file"], body="原始正文")
    provider = ScriptedProvider.from_streams(
        ((content_delta_event("first"), done_event()),)
    )
    tasks = BackgroundTaskManager()
    factory = make_factory(provider=provider, workspace=tmp_path)
    catalog = RoleCatalog(project_dir=role_dir, user_dir=tmp_path / "u", builtin_dir=tmp_path / "b")
    tool = AgentTool(catalog, factory, tasks, ConversationContext())
    context = ToolRunContext(
        ToolEnvironment.from_workspace(tmp_path), NORMAL_AGENT_MODE, PermissionState().snapshot()
    )
    prepared = tool.prepare({"type": "definition", "task": "快照任务", "role": "reader"}, context)
    result = await tool.execute(prepared, context)
    assert result.ok

    # The role body was frozen at launch: the first request contains the old body.
    first_request = provider.requests[0]
    first_text = "\n".join(str(message.get("content", "")) for message in first_request.messages)
    assert "原始正文" in first_text

    write_role(role_dir / "reader.md", name="reader", allow=["read_file"], body="修改后正文")
    catalog.refresh(factory.tool_registry.descriptors())
    assert catalog.snapshot.get("reader").system_prompt == "修改后正文" + chr(10)
    assert "原始正文" in first_text


async def test_completion_callback_failure_does_not_change_task_state(
    tmp_path: Path,
) -> None:
    """F17: an observer failure never turns a completed task into failure."""
    role_dir = tmp_path / ".artcode" / "agents"
    write_role(role_dir / "reader.md", name="reader", allow=["read_file"])
    provider = ScriptedProvider.from_streams(
        ((content_delta_event("done"), done_event()),)
    )

    def broken_callback(detail) -> None:
        raise RuntimeError("observer bug")

    tasks = BackgroundTaskManager(on_completed=broken_callback)
    factory = make_factory(provider=provider, workspace=tmp_path)
    tool = AgentTool(
        RoleCatalog(project_dir=role_dir, user_dir=tmp_path / "u", builtin_dir=tmp_path / "b"),
        factory,
        tasks,
        ConversationContext(),
    )
    context = ToolRunContext(
        ToolEnvironment.from_workspace(tmp_path), NORMAL_AGENT_MODE, PermissionState().snapshot()
    )
    prepared = tool.prepare({"type": "definition", "task": "通知任务", "role": "reader"}, context)
    result = await tool.execute(prepared, context)

    assert result.ok
    detail = tasks.get(__import__("json").loads(result.content)["task_id"])
    assert detail is not None and detail.status.value == "completed"
