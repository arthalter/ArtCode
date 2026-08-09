from __future__ import annotations

import re

from artcode.agent import (
    AgentEventType,
    AgentLoop,
    AgentRunRequest,
    NORMAL_AGENT_MODE,
    RequestPreparer,
)
from artcode.config import ContextConfig
from artcode.context_management import (
    ContextArtifactStore,
    ContextManager,
    ContextSummarizer,
    LightweightCompactor,
)
from artcode.context_management.retention import RetentionPlanner
from artcode.context_management.summarizer import SUMMARY_TITLES, VERBATIM_PLACEHOLDER
from artcode.conversation import ConversationContext
from artcode.permissions import PermissionState
from artcode.permissions.service import PermissionService
from artcode.prompting.assembler import PromptRequestAssembler
from artcode.providers.events import content_delta_event, done_event, token_usage_event, tool_calls_event
from artcode.providers.tool_calls import ToolCall
from artcode.tools import (
    DescriptorBackedTool,
    PreparedToolCall,
    ToolDescriptor,
    ToolEffect,
    ToolEnvironment,
    ToolPreview,
    ToolRegistry,
    ToolRunContext,
    success_result,
)
from artcode.tools.execution import ToolExecutionService
from artcode.tools.file_tools import ReadFileTool


def valid_summary() -> str:
    sections = []
    for index, title in enumerate(SUMMARY_TITLES, start=1):
        body = VERBATIM_PLACEHOLDER if index == 6 else f"本地摘要内容 {index}"
        sections.append(f"## {index}. {title}\n{body}")
    return "<analysis>internal draft</analysis><summary>" + "\n\n".join(sections) + "</summary>"


class FlowProvider:
    def __init__(self) -> None:
        self.responses = [
            [tool_calls_event([ToolCall("large-call", "large_output", "{}")]), done_event()],
            [content_delta_event(valid_summary()), done_event()],
            [content_delta_event("任务继续完成"), token_usage_event(prompt_tokens=321), done_event()],
        ]
        self.calls = []

    async def stream(self, request):
        self.calls.append(request)
        for event in self.responses.pop(0):
            yield event


class ScenarioEstimator:
    def __init__(self) -> None:
        self.anchor = None

    def estimate_request(self, messages, tools):
        text = str(messages)
        if "<conversation-summary>" in text:
            return 10_000
        if "<persisted-output>" in text:
            return 850_000
        return 100

    def record_usage(self, prompt_tokens, messages, tools):
        self.anchor = (prompt_tokens, list(messages), tools)


class LargeOutputTool(DescriptorBackedTool):
    descriptor = ToolDescriptor(
        "large_output",
        "产生多行大结果",
        {"type": "object", "properties": {}},
        ToolEffect.READ,
    )

    def prepare(self, arguments, context):
        return PreparedToolCall(self, arguments, ToolPreview(self.name, "large", "large"))

    async def execute(self, prepared, context):
        content = "".join(f"row-{index:05d}\n" for index in range(9_000)) + "UNIQUE_CONTEXT_TAIL\n"
        return success_result(self.name, "ok", content)


async def test_complete_context_management_flow(tmp_path) -> None:
    conversation = ConversationContext("system")
    for index in range(10):
        if index % 2 == 0:
            conversation.append_user(f"历史请求 {index}")
        else:
            conversation.append_assistant("历史回复 " + "x" * 100)
    provider = FlowProvider()
    store = ContextArtifactStore(tmp_path, "flow-session")
    store.start()
    environment = ToolEnvironment.from_workspace(
        tmp_path,
        artifact_store=store,
    )
    permission_state = PermissionState()
    registry = ToolRegistry()
    registry.register(LargeOutputTool())
    manager = ContextManager(
        ContextConfig(),
        ContextSummarizer(provider, conversation),
        estimator=ScenarioEstimator(),
        lightweight_compactor=LightweightCompactor(store),
        retention_planner=RetentionPlanner(recent_token_budget=50, minimum_messages=3),
    )
    preparer = RequestPreparer(
        conversation,
        PromptRequestAssembler(),
        registry,
        environment,
        permission_state,
        context_manager=manager,
    )
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
        request_preparer=preparer,
        context_manager=manager,
    )

    events = [
        event
        async for event in loop.run(
            AgentRunRequest("运行完整上下文场景", NORMAL_AGENT_MODE, max_iterations=3)
        )
    ]

    assert len(provider.calls) == 3
    assert provider.calls[1].tools is None
    assert provider.calls[1].thinking_enabled is False
    final_request = provider.calls[2].messages
    assert any(str(message.get("content", "")).startswith("<conversation-summary>") for message in final_request)
    artifact_message = next(message for message in final_request if message.get("role") == "tool")
    assert artifact_message["content"].startswith("<persisted-output>")
    assert any(
        event.type == AgentEventType.CONTEXT_STATUS
        and event.payload["trigger"] == "automatic"
        and event.payload["status"] == "success"
        for event in events
    )
    assert conversation.export_messages()[-1]["content"] == "任务继续完成"
    assert manager.estimator.anchor[0] == 321

    relative_path = re.search(r"^path: (.+)$", artifact_message["content"], re.MULTILINE).group(1)
    tool = ReadFileTool()
    run_context = ToolRunContext(
        environment,
        NORMAL_AGENT_MODE,
        permission_state.snapshot(),
    )
    prepared = tool.prepare(
        {"path": relative_path, "start_line": 8_999, "end_line": 9_001},
        run_context,
    )
    assert isinstance(prepared, PreparedToolCall)
    fragment = await tool.execute(prepared, run_context)
    assert "UNIQUE_CONTEXT_TAIL" in fragment.content

    session_dir = store.session_dir
    store.close()
    assert not session_dir.exists()
