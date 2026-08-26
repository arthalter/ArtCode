from __future__ import annotations

import json
from pathlib import Path

NL = chr(10)

import pytest

pytestmark = pytest.mark.live

from artcode.agent import NORMAL_AGENT_MODE
from artcode.background import BackgroundTaskManager
from artcode.config import ContextConfig
from artcode.conversation import ConversationContext
from artcode.permissions import PermissionMode, PermissionState
from artcode.providers import DeepSeekChatProvider
from artcode.subagents import RoleCatalog
from artcode.subagents.factory import SubagentFactory
from artcode.subagents.tool import AgentTool
from artcode.tools import ToolEnvironment, ToolRunContext, create_default_tool_registry
from artcode.worktrees import WorktreeManager
from tests.fixtures.git_repositories import init_repository, run_git
from tests.fixtures.subagents import write_role
from tests.live.conftest import make_live_provider


async def test_parallel_write_worktrees_e2e(tmp_path: Path) -> None:
    """E2E-01: two writing sub-agents modify the same file name in separate
    worktrees from the same recorded baseline; the main workspace file stays
    untouched and both results carry handoff details."""
    init_repository(
        tmp_path,
        files={"shared.txt": "main workspace original" + NL},
    )
    # E2E-01: the main workspace carries uncommitted state that must never
    # be copied into the sub-agent worktrees.
    (tmp_path / "uncommitted.txt").write_text("main uncommitted secret", encoding="utf-8")
    with open(tmp_path / "shared.txt", "a", encoding="utf-8") as handle:
        handle.write("main uncommitted line" + NL)
    role_dir = tmp_path / ".artcode" / "agents"
    write_role(
        role_dir / "writer.md",
        name="writer",
        allow=["read_file", "write_file"],
        isolation="worktree",
        permission_mode="edit",
        body=(
            "你负责在隔离的 Worktree 中修改 shared.txt：先用 read_file 读取，"
            "再在文件末尾追加一行以你的署名结尾的内容；不要创建其他文件。"
        ),
    )
    provider, client = make_live_provider()
    try:
        registry = create_default_tool_registry()
        environment = ToolEnvironment.from_workspace(tmp_path)
        tasks = BackgroundTaskManager()
        factory = SubagentFactory(
            provider=provider,
            tool_registry=registry,
            base_environment=environment,
            permission_engine=None,
            context_config=ContextConfig(),
            worktrees=WorktreeManager(tmp_path),
            model_tiers={},
            background_tools=frozenset(
                {"read_file", "write_file", "edit_file", "run_command", "find_files", "search_text"}
            ),
        )
        tool = AgentTool(
            RoleCatalog(
                project_dir=role_dir,
                user_dir=tmp_path / "user",
                builtin_dir=tmp_path / "builtin",
            ),
            factory,
            tasks,
            ConversationContext(),
        )
        state = PermissionState(mode=PermissionMode.EDIT)
        context = ToolRunContext(environment, NORMAL_AGENT_MODE, state.snapshot())

        first = await tool.execute(
            tool.prepare(
                {"type": "definition", "task": "以 ALPHA 的身份修改 shared.txt", "role": "writer"},
                context,
            ),
            context,
        )
        second = await tool.execute(
            tool.prepare(
                {"type": "definition", "task": "以 BETA 的身份修改 shared.txt", "role": "writer"},
                context,
            ),
            context,
        )
        assert first.ok, first.message
        assert second.ok, second.message
        await tasks.wait_all()

        def detail_of(payload_text: str):
            detail = tasks.get(json.loads(payload_text)["task_id"])
            assert detail is not None and detail.result is not None
            return detail

        first_detail = detail_of(first.content)
        second_detail = detail_of(second.content)
        first_handoff = first_detail.result.handoff
        second_handoff = second_detail.result.handoff
        assert first_handoff is not None and second_handoff is not None
        assert first_handoff.path != second_handoff.path
        assert first_handoff.branch != second_handoff.branch
        assert first_handoff.baseline == second_handoff.baseline

        first_text = (first_handoff.path / "shared.txt").read_text(encoding="utf-8")
        second_text = (second_handoff.path / "shared.txt").read_text(encoding="utf-8")
        assert "ALPHA" in first_text
        assert "BETA" in second_text
        # Main workspace untouched by the sub-agents.
        assert "main uncommitted line" in (tmp_path / "shared.txt").read_text(encoding="utf-8")
        # Uncommitted main-workspace state was never copied into the worktrees.
        for handoff in (first_handoff, second_handoff):
            assert not (handoff.path / "uncommitted.txt").exists()
            assert "main uncommitted line" not in (handoff.path / "shared.txt").read_text(encoding="utf-8")
        # Both handoffs mark the retained state honestly.
        assert first_handoff.retained is True
        assert second_handoff.retained is True
        assert first_handoff.commits_ahead == 0
        # The branch records exist in the main repository.
        branches = {
            line.strip().lstrip("* ").strip()
            for line in run_git(tmp_path, "branch", "--format=%(refname:short)").splitlines()
            if line.strip()
        }
        assert first_handoff.branch in branches
        assert second_handoff.branch in branches
    finally:
        await provider.close()
        await client.aclose()