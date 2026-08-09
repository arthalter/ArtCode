from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

pytestmark = pytest.mark.live

from artcode.agent import AgentLoop, AgentRunRequest, NORMAL_AGENT_MODE, ToolBatchExecutor
from artcode.config import load_config
from artcode.conversation import ConversationContext
from artcode.permissions import (
    ApprovalChoice,
    PermissionEngine,
    PermissionState,
    RuleLoader,
    RulePaths,
    RuleWriter,
)
from artcode.providers.openai_compatible import OpenAICompatibleProvider
from artcode.sandbox import SeatbeltSession
from artcode.security import DangerousCommandValidator
from artcode.tools import ToolExecutionContext, ToolRegistry, WorkspacePathPolicy
from artcode.tools.file_tools import EditFileTool, ReadFileTool
from artcode.workspace import Workspace


class AllowOnceApprover:
    def __init__(self) -> None:
        self.requests = []

    async def request_approval(self, request):
        self.requests.append(request)
        return ApprovalChoice.ALLOW_ONCE


async def test_live_deepseek_read_approve_edit_verify_and_summarize(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    target = workspace_root / "note.txt"
    target.write_text("状态：BEFORE_CH06\n", encoding="utf-8")

    workspace = Workspace.from_path(workspace_root)
    rule_paths = RulePaths(
        user=tmp_path / "home" / "permissions.yml",
        project=workspace.project_permissions_file,
        local=workspace.local_permissions_file,
    )
    rules = RuleLoader(rule_paths)
    sensitive_paths = (
        Path.home() / ".artcode" / "config.yml",
        rule_paths.user,
        rule_paths.project,
        rule_paths.local,
    )
    seatbelt = SeatbeltSession(workspace.root, sensitive_paths)
    await seatbelt.start()

    try:
        state = PermissionState()
        tool_context = ToolExecutionContext(
            WorkspacePathPolicy(workspace, sensitive_paths),
            default_cwd=workspace.root,
            shell_policy=state.shell_policy,
            seatbelt=seatbelt,
            permission_state=state,
        )
        registry = ToolRegistry()
        registry.register(ReadFileTool())
        registry.register(EditFileTool())

        approver = AllowOnceApprover()
        executor = ToolBatchExecutor(
            registry,
            tool_context,
            permission_engine=PermissionEngine(rules, DangerousCommandValidator.load()),
            permission_state=state,
            approver=approver,
            rule_writer=RuleWriter(rules),
        )
        config = replace(
            load_config(Path.home() / ".artcode" / "config.yml"),
            model="deepseek-v4-flash",
            workspace=workspace.root,
        )
        context = ConversationContext()
        provider = OpenAICompatibleProvider(config)
        loop = AgentLoop(
            provider=provider,
            conversation=context,
            tool_registry=registry,
            tool_context=tool_context,
            tool_executor=executor,
        )

        events = [
            event
            async for event in loop.run(
                AgentRunRequest(
                    user_content=(
                        "必须严格按顺序完成下面的任务："
                        "先调用 read_file 读取 note.txt；"
                        "再调用 edit_file，把唯一原文 BEFORE_CH06 替换为 AFTER_CH06；"
                        "编辑获批后必须再次调用 read_file 验证；"
                        "最后用一句中文总结。不得跳过工具，也不要猜测文件内容。"
                    ),
                    mode=NORMAL_AGENT_MODE,
                    max_iterations=6,
                )
            )
        ]

        messages = context.export_messages()
        tool_messages = [message for message in messages if message.get("role") == "tool"]
        payloads = [json.loads(message["content"]) for message in tool_messages]

        assert events[-1].payload["reason"] == "natural"
        assert [payload["tool_name"] for payload in payloads].count("read_file") >= 2
        assert [payload["tool_name"] for payload in payloads].count("edit_file") == 1
        assert len(approver.requests) == 1
        assert approver.requests[0].tool_name == "edit_file"
        assert target.read_text(encoding="utf-8") == "状态：AFTER_CH06\n"
        assert not rule_paths.local.exists()
        assert messages[-1]["role"] == "assistant"
        assert messages[-1]["content"].strip()
        assert not any(
            str(message.get("content", "")).startswith("<system-reminder>")
            for message in messages
        )
    finally:
        seatbelt.close()
