from __future__ import annotations

from pathlib import Path

from rich.console import Console

from artcode.agent import PlanMemory
from artcode.agent import RequestPreparer
from artcode.config import ArtCodeConfig, ThinkingConfig
from artcode.conversation import ConversationContext
from artcode.providers.events import content_delta_event, done_event, tool_calls_event
from artcode.providers.tool_calls import ToolCall
from artcode.runtime import ArtCodeRuntime
from artcode.context_management import ContextManager, ContextSummarizer
from artcode.persistence import PersistenceCoordinator, SessionSelection
from artcode.prompting.assembler import PromptRequestAssembler
from artcode.tools import AllowedPathPolicy, ToolExecutionContext, ToolRegistry
from artcode.workspace import ArtCodePaths, Workspace
import pytest
from artcode.tui import PromptToolkitTui, TuiRenderer


class FakeSession:
    def __init__(self, inputs: list[str]) -> None:
        self.inputs = inputs
        self.prompts: list[str] = []

    async def prompt_async(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.inputs.pop(0)


class FakeProvider:
    def __init__(self, responses: list[list[dict]]) -> None:
        self.responses = responses
        self.messages_seen: list[list[dict]] = []
        self.tools_seen: list[list[dict] | None] = []

    async def stream_chat(self, messages, tools=None, *, options=None):
        self.messages_seen.append(list(messages))
        self.tools_seen.append(tools)
        for event in self.responses.pop(0):
            yield event


class RecordingRenderer(TuiRenderer):
    def __init__(self) -> None:
        super().__init__(Console(record=True, width=120, force_terminal=True))
        self.clear_count = 0

    def clear_screen(self) -> None:
        self.clear_count += 1
        super().clear_screen()


def config_for(root: Path) -> ArtCodeConfig:
    root.mkdir()
    return ArtCodeConfig(
        protocol="openai",
        model="deepseek-v4-flash",
        base_url="https://api.deepseek.com",
        api_key="sk-integration-secret",
        thinking=ThinkingConfig(),
        workspace=root,
    )


def tui_for(inputs: list[str]) -> tuple[PromptToolkitTui, RecordingRenderer, FakeSession]:
    renderer = RecordingRenderer()
    tui = PromptToolkitTui(renderer)
    session = FakeSession(inputs)
    tui._session = session
    return tui, renderer, session


async def test_plain_message_and_local_commands_take_mutually_exclusive_paths(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    context = ConversationContext()
    provider = FakeProvider([[content_delta_event("普通回复"), done_event()]])
    tui, renderer, session = tui_for(
        [
            "请解释 /help",
            " /Unknown\n这一行也不能进入 Agent",
            "/status",
            "/clear",
            "/exit",
        ]
    )
    runtime = ArtCodeRuntime(config_for(workspace), provider, context, tui)

    assert await runtime.run() == 0

    assert len(provider.messages_seen) == 1
    assert context.export_messages()[-2:] == [
        {"role": "user", "content": "请解释 /help"},
        {"role": "assistant", "content": "普通回复"},
    ]
    assert not any(
        str(message.get("content", "")).startswith("/")
        for message in context.export_messages()
    )
    assert renderer.clear_count == 1
    output = renderer.console.export_text()
    assert "/Unknown" in output
    assert "运行状态" in output
    assert "sk-integration-secret" not in output
    assert session.prompts == ["[DEFAULT] deepseek-v4-flash > "] * 5


async def test_plan_do_and_compatibility_commands_share_real_runtime_components(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    context = ConversationContext()
    memory = PlanMemory()
    provider = FakeProvider(
        [
            [content_delta_event("计划：创建 marker.txt，并写入 CH10_OK。"), done_event()],
            [
                tool_calls_event(
                    [
                        ToolCall(
                            "write_1",
                            "write_file",
                            '{"path":"marker.txt","content":"CH10_OK\\n"}',
                        )
                    ]
                ),
                done_event(),
            ],
            [content_delta_event("执行完成。"), done_event()],
        ]
    )
    tui, renderer, session = tui_for(
        [
            "/plan 创建 marker.txt\n内容必须是 CH10_OK",
            "/do",
            "/compact",
            "/sessions",
            "/memory",
            "/exit",
        ]
    )
    runtime = ArtCodeRuntime(
        config_for(workspace),
        provider,
        context,
        tui,
        plan_memory=memory,
    )

    assert await runtime.run() == 0

    assert memory.get() == "计划：创建 marker.txt，并写入 CH10_OK。"
    assert (workspace / "marker.txt").read_text(encoding="utf-8") == "CH10_OK\n"
    assert len(provider.messages_seen) == 3
    assert [tool["function"]["name"] for tool in provider.tools_seen[0]] == [
        "read_file",
        "find_files",
        "search_text",
    ]
    assert provider.tools_seen[1] is not None
    output = renderer.console.export_text()
    assert "[PLAN] User" in output
    assert "[DEFAULT] User" in output
    assert session.prompts == ["[DEFAULT] deepseek-v4-flash > "] * 6
    assert not any(
        str(message.get("content", "")) in {"/do", "/compact", "/sessions", "/memory"}
        for message in context.export_messages()
    )


@pytest.mark.ch10_5
@pytest.mark.parametrize("repeat", [1, 2, 3, 5, 10])
async def test_repeated_status_has_zero_model_context_and_persistence_side_effects(
    tmp_path: Path,
    repeat: int,
) -> None:
    root = tmp_path / "status-workspace"
    config = config_for(root)
    workspace = Workspace.from_path(root)
    provider = FakeProvider([])
    persistence = PersistenceCoordinator.start(
        ArtCodePaths.create(tmp_path / "status-home"),
        workspace,
        provider,
        SessionSelection.new(),
    )
    persistence.conversation.append_user("stable conversation")
    context_manager = ContextManager(
        config.context,
        ContextSummarizer(provider, persistence.conversation),
    )
    context_manager.estimator.record_usage(
        123,
        persistence.conversation.export_messages(),
        None,
    )
    registry = ToolRegistry()
    tool_context = ToolExecutionContext(
        AllowedPathPolicy((workspace.root,)), default_cwd=workspace.root
    )
    preparer = RequestPreparer(
        persistence.conversation,
        PromptRequestAssembler(),
        registry,
        tool_context,
        context_manager=context_manager,
        durable_prompt=persistence.prompt_context,
        resume_reminder_required=True,
    )
    tui, _renderer, _session = tui_for([*(["/status"] * repeat), "/exit"])
    runtime = ArtCodeRuntime(
        config,
        provider,
        persistence.conversation,
        tui,
        tool_registry=registry,
        tool_context=tool_context,
        workspace=workspace,
        context_manager=context_manager,
        request_preparer=preparer,
        persistence=persistence,
    )
    before_messages = persistence.conversation.export_messages()
    before_reminder = preparer.resume_reminder_pending
    before_anchor = context_manager.estimator.anchor
    before_circuit = (
        context_manager.circuit.consecutive_failures,
        context_manager.circuit.open,
        context_manager.circuit.forced_attempted,
    )
    before_session = persistence.journal.path.read_bytes()
    before_memory = {
        path: path.read_bytes()
        for root_path in (persistence.paths.user_memory_dir, persistence.paths.project_memory_dir)
        for path in root_path.iterdir()
        if path.is_file()
    }
    before_pending = persistence.memory_service.pending_count

    try:
        assert await runtime.run() == 0
        assert len(runtime.tui.renderer.console.export_text()) > 0
        assert provider.messages_seen == []
        assert persistence.conversation.export_messages() == before_messages
        assert preparer.resume_reminder_pending is before_reminder
        assert context_manager.estimator.anchor == before_anchor
        assert (
            context_manager.circuit.consecutive_failures,
            context_manager.circuit.open,
            context_manager.circuit.forced_attempted,
        ) == before_circuit
        assert persistence.journal.path.read_bytes() == before_session
        assert {
            path: path.read_bytes()
            for root_path in (persistence.paths.user_memory_dir, persistence.paths.project_memory_dir)
            for path in root_path.iterdir()
            if path.is_file()
        } == before_memory
        assert persistence.memory_service.pending_count == before_pending
    finally:
        await persistence.close()
