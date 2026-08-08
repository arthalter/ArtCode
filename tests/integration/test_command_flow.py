from __future__ import annotations

from pathlib import Path

from rich.console import Console

from artcode.agent import PlanMemory
from artcode.config import ArtCodeConfig, ThinkingConfig
from artcode.conversation import ConversationContext
from artcode.providers.events import content_delta_event, done_event, tool_calls_event
from artcode.providers.tool_calls import ToolCall
from artcode.runtime import ArtCodeRuntime
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
