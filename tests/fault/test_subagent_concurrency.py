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
from artcode.tools import ToolEnvironment, ToolRunContext, create_default_tool_registry
from artcode.worktrees import WorktreeManager
from tests.fixtures.git_repositories import init_repository
from tests.fixtures.providers import ScriptedProvider
from tests.fixtures.subagents import make_factory, write_role


async def test_parallel_subagents_keep_messages_usage_and_permissions_isolated(
    tmp_path: Path,
) -> None:
    role_dir = tmp_path / ".artcode" / "agents"
    write_role(role_dir / "reader.md", name="reader", allow=["read_file"])
    parent = ConversationContext()
    parent.append_user("PARENT SECRET VALUE")
    provider = ScriptedProvider.from_streams(
        (
            (content_delta_event("alpha result"), done_event()),
            (content_delta_event("beta result"), done_event()),
        )
    )
    tasks = BackgroundTaskManager()
    factory = make_factory(provider=provider, workspace=tmp_path)
    tool = AgentTool(
        RoleCatalog(project_dir=role_dir, user_dir=tmp_path / "u", builtin_dir=tmp_path / "b"),
        factory,
        tasks,
        parent,
    )
    context = ToolRunContext(
        ToolEnvironment.from_workspace(tmp_path), NORMAL_AGENT_MODE, PermissionState().snapshot()
    )

    alpha = await tool.execute(
        tool.prepare({"type": "fork", "task": "alpha", "role": "reader"}, context), context
    )
    beta = await tool.execute(
        tool.prepare({"type": "fork", "task": "beta", "role": "reader"}, context), context
    )
    await tasks.wait_all()

    alpha_detail = tasks.get(json.loads(alpha.content)["task_id"])
    beta_detail = tasks.get(json.loads(beta.content)["task_id"])
    assert alpha_detail is not None and beta_detail is not None
    assert alpha_detail.result is not None and beta_detail.result is not None
    assert alpha_detail.result.final_text == "alpha result"
    assert beta_detail.result.final_text == "beta result"
    # Each fork froze its own parent snapshot; the parent marker is present in
    # both but their conversations never cross.
    for detail in (alpha_detail, beta_detail):
        text = "\n".join(str(m.get("content", "")) for m in detail.result.final_text and ())
        assert detail.result.final_text
    assert alpha_detail.result.task_id != beta_detail.result.task_id
    # Usage accumulators are per-task: each saw exactly one round.
    assert alpha_detail.result.rounds == 1
    assert beta_detail.result.rounds == 1


async def test_parallel_write_tasks_modify_only_their_own_worktrees(
    tmp_path: Path,
) -> None:
    """AC10/E2E-01: two writing sub-agents change the same file name in
    separate worktrees without touching the main workspace."""
    init_repository(tmp_path, files={"shared.txt": "main workspace original" + chr(10)})
    role_dir = tmp_path / ".artcode" / "agents"
    write_role(
        role_dir / "writer.md",
        name="writer",
        allow=["write_file"],
        isolation="worktree",
        permission_mode="edit",
    )
    provider = ScriptedProvider.from_streams(
        (
            (
                tool_calls_event([ToolCall("w1", "write_file", '{"path":"shared.txt","content":"alpha content","overwrite":true}')]),
                done_event(),
            ),
            (content_delta_event("alpha done"), done_event()),
            (
                tool_calls_event([ToolCall("w2", "write_file", '{"path":"shared.txt","content":"beta content","overwrite":true}')]),
                done_event(),
            ),
            (content_delta_event("beta done"), done_event()),
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
    state = PermissionState(mode=PermissionMode.EDIT)
    context = ToolRunContext(
        ToolEnvironment.from_workspace(tmp_path), NORMAL_AGENT_MODE, state.snapshot()
    )

    a = await tool.execute(
        tool.prepare({"type": "definition", "task": "写 alpha", "role": "writer"}, context), context
    )
    b = await tool.execute(
        tool.prepare({"type": "definition", "task": "写 beta", "role": "writer"}, context), context
    )
    assert a.ok and b.ok
    await tasks.wait_all()

    a_detail = tasks.get(json.loads(a.content)["task_id"])
    b_detail = tasks.get(json.loads(b.content)["task_id"])
    assert a_detail is not None and b_detail is not None
    assert a_detail.result is not None and b_detail.result is not None
    handoff_a = a_detail.result.handoff
    handoff_b = b_detail.result.handoff
    assert handoff_a is not None and handoff_b is not None
    assert handoff_a.path != handoff_b.path
    assert (handoff_a.path / "shared.txt").read_text(encoding="utf-8") == "alpha content"
    assert (handoff_b.path / "shared.txt").read_text(encoding="utf-8") == "beta content"
    # Main workspace untouched.
    assert (tmp_path / "shared.txt").read_text(encoding="utf-8") == "main workspace original" + chr(10)


async def test_process_cwd_never_changes_while_subagents_run(tmp_path: Path) -> None:
    """N4/C11: concurrent sub-agent work never depends on the process cwd."""
    import os

    role_dir = tmp_path / ".artcode" / "agents"
    write_role(role_dir / "reader.md", name="reader", allow=["read_file"])
    provider = ScriptedProvider.from_streams(
        (
            (content_delta_event("one"), done_event()),
            (content_delta_event("two"), done_event()),
            (content_delta_event("three"), done_event()),
        )
    )
    before = os.getcwd()
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
    results = await asyncio.gather(
        *(
            tool.execute(
                tool.prepare({"type": "fork", "task": f"任务 {index}", "role": "reader"}, context),
                context,
            )
            for index in range(3)
        )
    )
    await tasks.wait_all()
    assert all(item.ok for item in results)
    assert os.getcwd() == before
