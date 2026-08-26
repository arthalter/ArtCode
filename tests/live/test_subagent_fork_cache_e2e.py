from __future__ import annotations

import json
from pathlib import Path

NL = chr(10)

import pytest

pytestmark = pytest.mark.live

from artcode.agent import NORMAL_AGENT_MODE, RequestPreparer
from artcode.background import BackgroundTaskManager
from artcode.config import ContextConfig
from artcode.conversation import ConversationContext
from artcode.permissions import PermissionState
from artcode.providers import DeepSeekChatProvider
from artcode.prompting.assembler import PromptRequestAssembler
from artcode.subagents import RoleCatalog
from artcode.subagents.factory import SubagentFactory
from artcode.subagents.tool import AgentTool
from artcode.tools import ToolEnvironment, ToolRunContext, create_default_tool_registry
from artcode.worktrees import WorktreeManager
from tests.fixtures.subagents import write_role
from tests.live.conftest import make_live_provider


class _RecordingProvider:
    """Records every model request while delegating to the real provider."""

    def __init__(self, inner: DeepSeekChatProvider) -> None:
        self.inner = inner
        self.requests: list[object] = []

    async def stream(self, request):
        self.requests.append(request)
        async for event in self.inner.stream(request):
            yield event

    async def close(self) -> None:
        await self.inner.close()


async def test_fork_answers_from_parent_history_e2e(tmp_path: Path) -> None:
    """H07: a fork answers questions that depend on parent history; its first
    request keeps the parent message prefix and the task detail reports the
    real provider cache usage or honestly marks it unavailable."""
    inner, client = make_live_provider()
    provider = _RecordingProvider(inner)
    try:
        role_dir = tmp_path / ".artcode" / "agents"
        write_role(role_dir / "reader.md", name="reader", allow=["read_file"])
        registry = create_default_tool_registry()
        environment = ToolEnvironment.from_workspace(tmp_path)
        parent = ConversationContext(system_prompt="你是一个简短助手。")
        parent.append_user("请记住暗号：blue42。")
        parent.append_assistant("已记住：blue42。")
        # Simulate the parent request that the fork will inherit as prefix.
        preparer = RequestPreparer(
            parent,
            PromptRequestAssembler(),
            registry,
            environment,
            PermissionState(),
        )
        parent_request = preparer.preview_request(NORMAL_AGENT_MODE)
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
            parent_request_provider=lambda: parent_request,
            parent_policy_provider=lambda: NORMAL_AGENT_MODE.tool_policy,
        )
        context = ToolRunContext(
            environment, NORMAL_AGENT_MODE, PermissionState().snapshot()
        )
        prepared = tool.prepare(
            {
                "type": "fork",
                "task": "父对话中的暗号是什么？只回答暗号。",
                "role": "reader",
            },
            context,
        )
        result = await tool.execute(prepared, context)

        assert result.ok, result.message
        task_id = json.loads(result.content)["task_id"]
        detail = await tasks.wait(task_id)
        assert detail is not None and detail.result is not None
        assert "blue42" in detail.result.final_text
        # First request keeps the exact parent prefix, in order.
        assert provider.requests
        child_request = provider.requests[0]
        prefix = tuple(parent_request.messages)
        assert tuple(child_request.messages[: len(prefix)]) == prefix
        assert detail.result.cache_prefix_preserved is True
        # Usage is the provider's real report; a missing cache field is shown
        # as unknown rather than fabricated.
        usage = detail.result.usage
        assert usage.reported_rounds >= 1
        if usage.cached_tokens is not None:
            assert usage.cached_tokens >= 0
        if usage.total_tokens is not None:
            assert usage.total_tokens > 0
    finally:
        await provider.close()
        await client.aclose()