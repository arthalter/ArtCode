from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from artcode.commands import (
    CommandDispatcher,
    CommandFlow,
    create_default_registry,
    parse_input,
)
from artcode.tools import ToolEnvironment, ToolRunContext, create_default_tool_registry
from artcode.agent import NORMAL_AGENT_MODE
from artcode.background import BackgroundTaskManager
from artcode.config import ContextConfig
from artcode.conversation import ConversationContext
from artcode.permissions import PermissionMode, PermissionState
from artcode.providers.events import content_delta_event, done_event
from artcode.subagents import RoleCatalog
from artcode.subagents.factory import SubagentFactory
from artcode.subagents.tool import AgentTool
from artcode.worktrees import WorktreeManager
from tests.fixtures.git_repositories import init_repository, worktree_list
from tests.fixtures.providers import ScriptedProvider
from tests.fixtures.subagents import make_factory, write_role


class _FakeTui:
    def __init__(self) -> None:
        self.answers: list[bool] = []
        self.help_messages: list[str] = []
        self.error_messages: list[str] = []
        self.discard_prompts: list[tuple[str, Path, str, object]] = []

    def show_help(self, message: str) -> None:
        self.help_messages.append(message)

    def show_error(self, message: str) -> None:
        self.error_messages.append(message)

    async def confirm_worktree_discard(self, task_id, path, branch, status) -> bool:
        self.discard_prompts.append((task_id, path, branch, status))
        return self.answers.pop(0)


async def _retained_worktree(tmp_path: Path) -> tuple[WorktreeManager, str, Path, str]:
    init_repository(tmp_path)
    manager = WorktreeManager(tmp_path)
    baseline = manager.capture_baseline()
    lease = manager.acquire("task-12345678", baseline)
    (lease.path / "dirty.txt").write_text("keep", encoding="utf-8")
    manager.handoff(lease)
    assert lease.path.exists()
    return manager, lease.task_id, lease.path, lease.branch


def _make_controller(tmp_path: Path, tui: _FakeTui, manager: WorktreeManager):
    from artcode.runtime.app import ArtCodeRuntime

    return ArtCodeRuntime(
        config=None,
        conversation=ConversationContext(),
        tui=tui,
        workspace=None,
        state=None,
        tool_environment=None,
        plan_memory=None,
        agent_loop=None,
        command_dispatcher=None,
        session_service=None,
        memory_service=None,
        startup_status=None,
        mcp_report=None,
        skill_service=None,
        task_manager=BackgroundTaskManager(),
        worktree_manager=manager,
        startup_worktree_diagnostics=(),
    )


async def test_worktree_drop_command_requires_task_id() -> None:
    registry = create_default_registry()
    controller = _make_controller(
        __import__("pathlib").Path("."), _FakeTui(), WorktreeManager(__import__("pathlib").Path("."))
    )
    result = await CommandDispatcher(registry).dispatch(
        parse_input("/worktree-drop").invocation, controller
    )
    assert result is CommandFlow.CONTINUE


async def test_worktree_drop_cancelled_by_user_removes_nothing(tmp_path: Path) -> None:
    manager, task_id, path, _ = await _retained_worktree(tmp_path)
    tui = _FakeTui()
    tui.answers.append(False)
    controller = _make_controller(tmp_path, tui, manager)

    await controller.drop_worktree(task_id)

    assert path.exists()
    assert any("已取消丢弃" in message for message in tui.help_messages)
    assert str(path) in worktree_list(tmp_path)


async def test_worktree_drop_confirmed_removes_worktree_and_branch(tmp_path: Path) -> None:
    manager, task_id, path, branch = await _retained_worktree(tmp_path)
    tui = _FakeTui()
    tui.answers.append(True)
    controller = _make_controller(tmp_path, tui, manager)

    await controller.drop_worktree(task_id)

    assert not path.exists()
    assert str(path) not in worktree_list(tmp_path)
    assert any("已丢弃 Worktree" in message for message in tui.help_messages)
    # The confirmation dialog received the full loss statistics (G13).
    assert len(tui.discard_prompts) == 1
    prompted_task_id, prompted_path, prompted_branch, status = tui.discard_prompts[0]
    assert prompted_task_id == task_id
    assert prompted_path == path
    assert prompted_branch == branch
    assert status.untracked_changes == 1
    assert status.tracked_changes == 0
    assert status.commits_ahead == 0


async def test_worktree_drop_rejects_unknown_or_running_task(tmp_path: Path) -> None:
    manager, task_id, path, _ = await _retained_worktree(tmp_path)
    manager._active_task_ids.add(task_id)
    tui = _FakeTui()
    controller = _make_controller(tmp_path, tui, manager)

    await controller.drop_worktree(task_id)

    assert path.exists()
    assert any("仍在运行" in message for message in tui.help_messages)
