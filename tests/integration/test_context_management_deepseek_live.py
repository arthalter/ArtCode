from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

pytestmark = pytest.mark.live

from artcode.agent import AgentLoop, AgentRunRequest, NORMAL_AGENT_MODE, RequestPreparer
from artcode.config import ArtCodeConfig
from tests.live.conftest import load_live_config
from artcode.context_management import ContextManager, ContextSummarizer
from artcode.context_management.models import CompressionTrigger
from artcode.context_management.retention import RetentionPlanner
from artcode.context_management.summarizer import SUMMARY_TITLES
from artcode.conversation import ConversationContext
from artcode.permissions import PermissionState
from artcode.permissions.service import PermissionService
from artcode.prompting.assembler import PromptRequestAssembler
from artcode.providers import DeepSeekChatProvider
from artcode.tools import ToolEnvironment, ToolRegistry
from artcode.tools.execution import ToolExecutionService


ROOT = Path(__file__).resolve().parents[2]


def required_live_config() -> ArtCodeConfig:
    return replace(load_live_config(), model="deepseek-v4-flash")


async def test_live_deepseek_summary_and_followup_preserve_user_intent(tmp_path) -> None:
    marker = "CH08-LIVE-CONTEXT-7429"
    config = required_live_config()
    provider = DeepSeekChatProvider(config)
    conversation = ConversationContext("你是简洁的上下文连续性测试助手。")
    conversation.append_user(f"请逐字记住暗号 {marker}，只回复已记住。")
    conversation.append_assistant("已记住。")
    for index in range(10):
        conversation.append_user(f"这是用于形成历史的第 {index} 条请求。")
        conversation.append_assistant(f"已记录第 {index} 条请求。")
    manager = ContextManager(
        config.context,
        ContextSummarizer(provider, conversation),
        retention_planner=RetentionPlanner(recent_token_budget=50, minimum_messages=3),
    )

    reports = []
    for _attempt in range(3):
        report = await manager.compact(conversation, CompressionTrigger.MANUAL)
        reports.append(report)
        if report.status == "success":
            break

    assert report.status == "success", [item.message for item in reports]
    messages = conversation.export_messages()
    summary = messages[1]["content"]
    assert summary.startswith("<conversation-summary>")
    assert "<analysis>" not in summary
    assert marker in summary
    assert all(title in summary for title in SUMMARY_TITLES)

    registry = ToolRegistry()
    environment = ToolEnvironment.from_workspace(tmp_path)
    permission_state = PermissionState()
    loop = AgentLoop(
        provider,
        conversation,
        registry,
        environment,
        tool_executor=ToolExecutionService(
            registry,
            environment,
            PermissionService(permission_state),
        ),
        request_preparer=RequestPreparer(
            conversation,
            PromptRequestAssembler(),
            registry,
            environment,
            permission_state,
            context_manager=manager,
        ),
        context_manager=manager,
    )
    events = [
        event
        async for event in loop.run(
            AgentRunRequest("最早要求你逐字记住的暗号是什么？只回复暗号。", NORMAL_AGENT_MODE)
        )
    ]

    assert events[-1].payload["reason"] == "natural"
    assert marker in conversation.export_messages()[-1]["content"]
