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
from artcode.subagents.tool import AgentTool
from artcode.tools import ToolEnvironment, ToolRunContext
from tests.fixtures.providers import ScriptedProvider
from tests.fixtures.subagents import make_factory, write_role


async def test_fork_snapshot_frozen_while_parent_keeps_changing(tmp_path: Path) -> None:
    """C06: messages queued into the parent after a fork launch do not
    change the already-frozen child snapshot."""
    role_dir = tmp_path / ".artcode" / "agents"
    write_role(role_dir / "reader.md", name="reader", allow=["read_file"])
    provider = ScriptedProvider.from_streams(
        ((content_delta_event("child sees frozen history"), done_event()),)
    )
    tasks = BackgroundTaskManager()
    factory = make_factory(provider=provider, workspace=tmp_path)
    parent = ConversationContext()
    parent.append_user("父对话唯一标记 FROZEN-1")
    tool = AgentTool(
        RoleCatalog(project_dir=role_dir, user_dir=tmp_path / "u", builtin_dir=tmp_path / "b"),
        factory, tasks, parent,
    )
    context = ToolRunContext(
        ToolEnvironment.from_workspace(tmp_path), NORMAL_AGENT_MODE, PermissionState().snapshot()
    )
    prepared = tool.prepare({"type": "fork", "task": "冻结任务", "role": "reader"}, context)

    result = await tool.execute(prepared, context)

    assert result.ok
    # The parent keeps talking after the fork was launched.
    parent.append_user("父对话后来新增 POST-FORK-2")
    await tasks.wait_all()
    child_request = provider.requests[0]
    child_text = "\n".join(str(m.get("content", "")) for m in child_request.messages)
    assert "FROZEN-1" in child_text
    assert "POST-FORK-2" not in child_text
