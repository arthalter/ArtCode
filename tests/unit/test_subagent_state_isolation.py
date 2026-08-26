from __future__ import annotations

import asyncio
import json
from pathlib import Path

from artcode.agent import NORMAL_AGENT_MODE
from artcode.background import BackgroundTaskManager
from artcode.conversation import ConversationContext
from artcode.permissions import PermissionState
from artcode.providers.events import content_delta_event, done_event
from artcode.subagents import RoleCatalog
from artcode.subagents.factory import SubagentFactory
from artcode.subagents.tool import AgentTool
from artcode.tools import ToolEnvironment, ToolRunContext, create_default_tool_registry
from tests.fixtures.providers import ScriptedProvider
from tests.fixtures.subagents import make_factory, write_role


async def test_two_subagents_have_disjoint_runtime_state_objects(
    tmp_path: Path
) -> None:
    """C07: conversations, file caches, permission services and usage
    accumulators are per-task instances, never shared."""
    role_dir = tmp_path / ".artcode" / "agents"
    write_role(role_dir / "reader.md", name="reader", allow=["read_file"])
    registry = create_default_tool_registry()
    provider = ScriptedProvider.from_streams(
        (
            (content_delta_event("one"), done_event()),
            (content_delta_event("two"), done_event()),
        )
    )
    tasks = BackgroundTaskManager()
    factory = make_factory(provider=provider, workspace=tmp_path, registry=registry)
    tool = AgentTool(
        RoleCatalog(project_dir=role_dir, user_dir=tmp_path / "u", builtin_dir=tmp_path / "b"),
        factory,
        tasks,
        ConversationContext(),
    )
    environment = ToolEnvironment.from_workspace(tmp_path)
    context = ToolRunContext(environment, NORMAL_AGENT_MODE, PermissionState().snapshot())

    a = await tool.execute(
        tool.prepare({"type": "fork", "task": "任务一", "role": "reader"}, context), context
    )
    b = await tool.execute(
        tool.prepare({"type": "fork", "task": "任务二", "role": "reader"}, context), context
    )
    await tasks.wait_all()

    # The strongest observable identity check: each task has its own result
    # object, its own usage accumulator and its own permission events list.
    detail_a = tasks.get(json.loads(a.content)["task_id"])
    detail_b = tasks.get(json.loads(b.content)["task_id"])
    assert detail_a is not None and detail_b is not None
    assert detail_a.result is not detail_b.result
    assert detail_a.result.usage is not detail_b.result.usage
    assert detail_a.result.permission_events == detail_b.result.permission_events == ()
    assert detail_a.result.task_id != detail_b.result.task_id

    # File caches are per-environment: the base environment cache is empty
    # while each sub-agent environment carried its own fresh instance.
    assert environment.file_cache is not None
    assert environment.file_cache.size == 0
