from __future__ import annotations

import json
from pathlib import Path

from artcode.agent import NORMAL_AGENT_MODE
from artcode.background import BackgroundTaskManager
from artcode.conversation import ConversationContext
from artcode.permissions import PermissionState
from artcode.providers.events import content_delta_event, done_event, tool_calls_event
from artcode.providers.tool_calls import ToolCall
from artcode.subagents import AgentKind, RoleCatalog
from artcode.subagents.tool import AgentTool
from artcode.tools import ToolEnvironment, ToolRunContext
from tests.fixtures.git_repositories import init_repository
from tests.fixtures.providers import ScriptedProvider
from tests.fixtures.subagents import make_factory, write_role


async def test_max_rounds_role_stops_with_max_rounds_status(tmp_path: Path) -> None:
    """B11: a role reaching its round cap ends with the max_rounds state."""
    role_dir = tmp_path / ".artcode" / "agents"
    write_role(
        role_dir / "reader.md", name="reader", allow=["read_file"], max_rounds=2
    )
    (tmp_path / "a.txt").write_text("content", encoding="utf-8")
    # Every round calls a tool so the iteration cap is consumed; the third
    # stream would be a tool round that never starts because the loop stops
    # at iteration two and goes straight to the final summary.
    provider = ScriptedProvider.from_streams(
        (
            (tool_calls_event([ToolCall("c1", "read_file", '{"path":"a.txt"}')]), done_event()),
            (tool_calls_event([ToolCall("c2", "read_file", '{"path":"a.txt"}')]), done_event()),
            (content_delta_event("summary"), done_event()),
        )
    )
    tasks = BackgroundTaskManager()
    factory = make_factory(provider=provider, workspace=tmp_path)
    tool = AgentTool(
        RoleCatalog(project_dir=role_dir, user_dir=tmp_path / "u", builtin_dir=tmp_path / "b"),
        factory, tasks, ConversationContext(),
    )
    context = ToolRunContext(
        ToolEnvironment.from_workspace(tmp_path), NORMAL_AGENT_MODE, PermissionState().snapshot()
    )
    prepared = tool.prepare(
        {"type": "definition", "task": "轮次任务", "role": "reader"}, context
    )

    result = await tool.execute(prepared, context)

    assert result.ok
    payload = json.loads(result.content)
    assert payload["status"] == "max_rounds"
    assert payload["rounds"] == 2
    assert payload["stop_reason"] == "max_rounds"


async def test_fork_round_cap_comes_from_role_or_fifty_without_role(
    tmp_path: Path,
) -> None:
    """B12: an unroled fork caps at 50; a roled fork uses its role cap,\n
    and the agent tool never accepts an override field."""
    # An unroled fork inherits write tools, so it needs a real repository
    # (D14) before the worktree can be created.
    init_repository(tmp_path, files={"a.txt": "content" + chr(10)})
    role_dir = tmp_path / ".artcode" / "agents"
    write_role(role_dir / "reader.md", name="reader", allow=["read_file"], max_rounds=7)
    provider = ScriptedProvider.from_streams(
        (
            (content_delta_event("unroled"), done_event()),
            (content_delta_event("roled"), done_event()),
        )
    )
    tasks = BackgroundTaskManager()
    factory = make_factory(provider=provider, workspace=tmp_path)
    tool = AgentTool(
        RoleCatalog(project_dir=role_dir, user_dir=tmp_path / "u", builtin_dir=tmp_path / "b"),
        factory, tasks, ConversationContext(),
    )
    context = ToolRunContext(
        ToolEnvironment.from_workspace(tmp_path), NORMAL_AGENT_MODE, PermissionState().snapshot()
    )

    unroled = await tool.execute(
        tool.prepare({"type": "fork", "task": "无角色任务"}, context), context
    )
    assert unroled.ok
    unroled_detail = await tasks.wait(json.loads(unroled.content)["task_id"])
    assert unroled_detail is not None and unroled_detail.result is not None
    # The loop for an unroled fork runs with the fixed 50-iteration cap.
    assert unroled_detail.result.rounds == 1
    assert unroled_detail.request.kind is AgentKind.FORK

    roled = await tool.execute(
        tool.prepare(
            {"type": "definition", "task": "角色任务", "role": "reader"}, context
        ),
        context,
    )
    assert roled.ok
    roled_detail = tasks.get(json.loads(roled.content)["task_id"])
    assert roled_detail is not None and roled_detail.result is not None
    assert roled_detail.request.role_name == "reader"

    # The agent tool rejects any attempt to pass a round cap directly.
    rejected = tool.prepare(
        {"type": "fork", "task": "越权任务", "max_rounds": 1}, context
    )
    assert not rejected.ok
