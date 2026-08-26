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
from artcode.permissions import PermissionState
from artcode.providers import DeepSeekChatProvider
from artcode.subagents import RoleCatalog
from artcode.subagents.factory import SubagentFactory
from artcode.subagents.tool import AgentTool
from artcode.tools import ToolEnvironment, ToolRunContext, create_default_tool_registry
from artcode.worktrees import WorktreeManager
from tests.fixtures.subagents import write_role
from tests.live.conftest import make_live_provider


class _RecordingProvider:
    """Records every model request while delegating to the real provider."""

    def __init__(self, inner) -> None:
        self.inner = inner
        self.requests: list[object] = []

    async def stream(self, request):
        self.requests.append(request)
        async for event in self.inner.stream(request):
            yield event

    async def close(self) -> None:
        await self.inner.close()


async def _execute_with_retry(tool, prepared, context, attempts: int = 2):
    """Retry once on flaky model-stream interruptions from the live API.

    Real provider streams occasionally end without a [DONE] event; the
    acceptance path should tolerate one retry but still fail honestly if
    the service stays broken.
    """
    last = None
    for _ in range(attempts):
        last = await tool.execute(prepared, context)
        if last.ok:
            return last
    return last


async def test_definition_read_only_e2e(tmp_path: Path) -> None:
    """H06: a definition sub-agent runs with a clean context and no worktree,
    returning only its conclusion and usage to the parent."""
    inner, client = make_live_provider()
    provider = _RecordingProvider(inner)
    try:
        target = tmp_path / "notes.txt"
        target.write_text("暗号 blue42 已经写在项目笔记里。" + NL, encoding="utf-8")
        role_dir = tmp_path / ".artcode" / "agents"
        write_role(
            role_dir / "reader.md",
            name="reader",
            allow=["read_file"],
            body="阅读项目文件并回答事实问题；直接给出简短结论，不要解释过程。",
        )
        parent = ConversationContext()
        parent.append_user("PARENT HISTORY UNIQUE MARKER 9f3a")
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
            parent,
        )
        context = ToolRunContext(
            environment, NORMAL_AGENT_MODE, PermissionState().snapshot()
        )
        prepared = tool.prepare(
            {
                "type": "definition",
                "task": "读取 notes.txt，回答暗号是什么。只回答暗号本身。",
                "role": "reader",
            },
            context,
        )
        result = await _execute_with_retry(tool, prepared, context)

        assert result.ok, result.message
        detail = tasks.get(json.loads(result.content)["task_id"])
        assert detail is not None and detail.result is not None
        # Clean definition context: the parent marker never leaks into the
        # child's requests.
        for request in provider.requests:
            text = NL.join(str(message.get("content", "")) for message in request.messages)
            assert "PARENT HISTORY UNIQUE MARKER" not in text
        # Read-only role: no worktree was created and no Git repository exists.
        assert detail.result.handoff is None
        # The conclusion and usage are returned; usage fields are either real
        # values or honestly unknown, never fabricated estimates.
        assert detail.result.final_text
        usage = detail.result.usage
        assert usage.reported_rounds >= 1
        if usage.total_tokens is not None:
            assert usage.total_tokens > 0
    finally:
        await provider.close()
        await client.aclose()
        await client.aclose()


async def test_definition_foreground_to_background_and_result_visibility(
    tmp_path: Path,
) -> None:
    """H08: a foreground definition task can finish naturally; the parent then
    sees one task detail with final text and usage (no duplicate notification
    is required for a foreground finish)."""
    provider, client = make_live_provider()
    try:
        role_dir = tmp_path / ".artcode" / "agents"
        write_role(role_dir / "reader.md", name="reader", allow=["read_file"])
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
        context = ToolRunContext(
            environment, NORMAL_AGENT_MODE, PermissionState().snapshot()
        )
        prepared = tool.prepare(
            {
                "type": "definition",
                "task": "用一句话说明 1+1 等于几，不要使用任何工具。",
                "role": "reader",
            },
            context,
        )
        result = await _execute_with_retry(tool, prepared, context)

        assert result.ok, result.message
        payload = json.loads(result.content)
        detail = tasks.get(payload["task_id"])
        assert detail is not None
        assert detail.status.value == "completed"
        assert detail.result is not None and detail.result.final_text
        assert detail.result.stop_reason.value == "natural"
        assert detail.result.rounds >= 1
    finally:
        await provider.close()