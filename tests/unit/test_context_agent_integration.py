from __future__ import annotations

from artcode.agent import AgentEventType, AgentLoop, AgentRunRequest, NORMAL_AGENT_MODE
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
from artcode.errors import ContextWindowExceededError
from artcode.errors import NetworkError
from artcode.providers.events import content_delta_event, done_event, token_usage_event, tool_calls_event
from artcode.providers.tool_calls import ToolCall
from artcode.tools import AllowedPathPolicy, PreparedToolCall, ToolExecutionContext, ToolPreview, ToolRegistry, success_result


def valid_summary() -> str:
    sections = []
    for index, title in enumerate(SUMMARY_TITLES, start=1):
        body = VERBATIM_PLACEHOLDER if index == 6 else f"内容 {index}"
        sections.append(f"## {index}. {title}\n{body}")
    return "<analysis>draft</analysis><summary>" + "\n\n".join(sections) + "</summary>"


class QueueProvider:
    def __init__(self, actions):
        self.actions = list(actions)
        self.calls = []

    async def stream_chat(self, messages, tools=None, *, options=None):
        self.calls.append((list(messages), tools, options))
        action = self.actions.pop(0)
        if isinstance(action, Exception):
            raise action
        for event in action:
            yield event


class LargeTool:
    name = "read_file"
    description = "large"
    parameters_schema = {"type": "object", "properties": {}}
    requires_confirmation = False

    def prepare(self, arguments, context):
        return PreparedToolCall(self, arguments, ToolPreview(self.name, "large", "large", False))

    async def execute(self, prepared, context):
        return success_result(self.name, "ok", "a" * 24_003 + "UNIQUE_TAIL")


def build_loop(tmp_path, provider, conversation, *, with_large_tool=False):
    store = ContextArtifactStore(tmp_path, "session")
    store.start()
    tool_context = ToolExecutionContext(
        AllowedPathPolicy((tmp_path,)),
        default_cwd=tmp_path,
        artifact_store=store,
    )
    registry = ToolRegistry()
    if with_large_tool:
        registry.register(LargeTool())
    summarizer = ContextSummarizer(provider, conversation)
    manager = ContextManager(
        ContextConfig(),
        summarizer,
        lightweight_compactor=LightweightCompactor(store),
        retention_planner=RetentionPlanner(recent_token_budget=50, minimum_messages=3),
    )
    return AgentLoop(provider, conversation, registry, tool_context, context_manager=manager), store


async def collect(loop, request):
    return [event async for event in loop.run(request)]


async def test_large_tool_result_is_persisted_before_next_model_request(tmp_path) -> None:
    provider = QueueProvider(
        [
            [tool_calls_event([ToolCall("call-1", "read_file", "{}")]), done_event()],
            [content_delta_event("done"), token_usage_event(prompt_tokens=123), done_event()],
        ]
    )
    conversation = ConversationContext("system")
    loop, store = build_loop(tmp_path, provider, conversation, with_large_tool=True)

    events = await collect(loop, AgentRunRequest("read", NORMAL_AGENT_MODE))

    second_request_tool = next(message for message in provider.calls[1][0] if message.get("role") == "tool")
    assert second_request_tool["content"].startswith("<persisted-output>")
    assert any(event.type == AgentEventType.CONTEXT_STATUS for event in events)
    files = list(store.tool_results_dir.iterdir())
    assert len(files) == 1
    assert files[0].read_text(encoding="utf-8").endswith("UNIQUE_TAIL")
    assert loop.context_manager.estimator.anchor.prompt_tokens == 123
    store.close()


def historical_context() -> ConversationContext:
    context = ConversationContext("system")
    for index in range(12):
        if index % 2 == 0:
            context.append_user(f"old user {index}")
        else:
            context.append_assistant("old assistant " + "x" * 100)
    return context


async def test_context_error_runs_one_emergency_compaction_and_retries_once(tmp_path) -> None:
    provider = QueueProvider(
        [
            ContextWindowExceededError("too long"),
            [content_delta_event(valid_summary()), done_event()],
            [content_delta_event("recovered"), done_event()],
        ]
    )
    conversation = historical_context()
    loop, store = build_loop(tmp_path, provider, conversation)

    events = await collect(loop, AgentRunRequest("continue", NORMAL_AGENT_MODE))

    assert len(provider.calls) == 3
    assert provider.calls[1][1] is None
    assert provider.calls[1][2].max_output_tokens == 20_000
    assert sum(
        message.get("role") == "user" and message.get("content") == "continue"
        for message in conversation.export_messages()
    ) == 1
    assert any(
        event.type == AgentEventType.CONTEXT_STATUS
        and event.payload["trigger"] == "emergency"
        and event.payload["status"] == "success"
        for event in events
    )
    store.close()


async def test_second_context_error_stops_without_recursive_summary(tmp_path) -> None:
    provider = QueueProvider(
        [
            ContextWindowExceededError("too long"),
            [content_delta_event(valid_summary()), done_event()],
            ContextWindowExceededError("still too long"),
        ]
    )
    conversation = historical_context()
    loop, store = build_loop(tmp_path, provider, conversation)

    events = await collect(loop, AgentRunRequest("continue", NORMAL_AGENT_MODE))

    assert len(provider.calls) == 3
    assert events[-1].payload["reason"] == "stream_error"
    store.close()


async def test_non_context_request_error_never_triggers_emergency_summary(tmp_path) -> None:
    provider = QueueProvider([NetworkError("offline")])
    conversation = historical_context()
    loop, store = build_loop(tmp_path, provider, conversation)

    events = await collect(loop, AgentRunRequest("continue", NORMAL_AGENT_MODE))

    assert len(provider.calls) == 1
    assert events[-1].payload["reason"] == "stream_error"
    assert not any(
        event.type == AgentEventType.CONTEXT_STATUS
        and event.payload["trigger"] == "emergency"
        for event in events
    )
    store.close()
