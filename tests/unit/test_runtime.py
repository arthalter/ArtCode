from __future__ import annotations

import json
from pathlib import Path

from artcode.agent import PlanMemory
from artcode.config import ArtCodeConfig, ThinkingConfig, ToolConfig
from artcode.conversation import ConversationContext
from artcode.providers.events import content_delta_event, done_event, tool_calls_event
from artcode.providers.tool_calls import ToolCall
from artcode.runtime import ArtCodeRuntime


class FakeTui:
    def __init__(self, inputs: list[str]) -> None:
        self.inputs = inputs
        self.output: list[str] = []
        self.confirmations_requested = 0

    def show_startup(self, status) -> None:
        self.output.append("startup")

    async def read_input(self, model: str) -> str:
        return self.inputs.pop(0)

    def show_help(self, message: str) -> None:
        self.output.append(f"help:{message}")

    def show_error(self, error) -> None:
        self.output.append(error.user_message)

    def show_cancelled(self) -> None:
        self.output.append("cancelled")

    def show_exit(self) -> None:
        self.output.append("exit")

    def show_user_label(self) -> None:
        self.output.append("user")

    def show_assistant_label(self) -> None:
        self.output.append("assistant")

    def stream_delta(self, text: str) -> None:
        self.output.append(text)

    def finish_assistant_message(self) -> None:
        self.output.append("done")

    def show_tool_preview(self, preview) -> None:
        self.output.append(f"preview:{preview.tool_name}")

    async def confirm_tool_execution(self, preview) -> bool:
        self.confirmations_requested += 1
        return False

    def show_tool_result_summary(self, result) -> None:
        self.output.append(f"tool:{result.status}:{result.error_code}")

    def show_agent_iteration(self, current: int, maximum: int) -> None:
        self.output.append(f"iteration:{current}/{maximum}")

    def show_tool_calls_received(self, count: int) -> None:
        self.output.append(f"tool_calls:{count}")

    def show_tool_batch_started(self, batch_index: int, safety: str, count: int) -> None:
        self.output.append(f"batch:{batch_index}:{safety}:{count}")

    def show_token_usage(self, prompt_tokens=None, completion_tokens=None, total_tokens=None) -> None:
        self.output.append(f"usage:{total_tokens}")

    def show_agent_stopped(self, reason: str, message: str = "") -> None:
        self.output.append(f"stopped:{reason}")


class FakeProvider:
    def __init__(self, responses: list[list[dict]]) -> None:
        self.responses = responses
        self.tools_seen: list[list[dict] | None] = []
        self.messages_seen: list[list[dict]] = []

    async def stream_chat(self, messages, tools=None):
        self.messages_seen.append(list(messages))
        self.tools_seen.append(tools)
        for event in self.responses.pop(0):
            yield event


def fake_config(root: Path) -> ArtCodeConfig:
    root.mkdir(exist_ok=True)
    return ArtCodeConfig(
        protocol="openai",
        model="deepseek-v4-flash",
        base_url="https://api.deepseek.com",
        api_key="sk-test",
        thinking=ThinkingConfig(),
        tools=ToolConfig((root,)),
    )


async def test_runtime_routes_plain_input_through_agent_loop(tmp_path) -> None:
    context = ConversationContext()
    tui = FakeTui(["你好", "/exit"])
    provider = FakeProvider([[content_delta_event("你好"), done_event()]])
    runtime = ArtCodeRuntime(fake_config(tmp_path / "sandbox"), provider, context, tui)

    await runtime.run()

    assert context.export_messages()[-2] == {"role": "user", "content": "你好"}
    assert context.export_messages()[-1] == {"role": "assistant", "content": "你好"}
    assert provider.tools_seen[0] is not None
    assert "iteration:1/12" in tui.output
    assert "stopped:natural" in tui.output


async def test_runtime_ignores_empty_input(tmp_path) -> None:
    context = ConversationContext()
    tui = FakeTui(["  ", "/exit"])
    provider = FakeProvider([])
    runtime = ArtCodeRuntime(fake_config(tmp_path / "sandbox"), provider, context, tui)

    await runtime.run()

    assert len(context.export_messages()) == 1


async def test_runtime_plan_saves_latest_plan(tmp_path) -> None:
    context = ConversationContext()
    memory = PlanMemory()
    tui = FakeTui(["/plan 加 Agent Loop", "/exit"])
    provider = FakeProvider([[content_delta_event("计划：先读后改"), done_event()]])
    runtime = ArtCodeRuntime(fake_config(tmp_path / "sandbox"), provider, context, tui, plan_memory=memory)

    await runtime.run()

    assert memory.get() == "计划：先读后改"
    tool_names = [tool["function"]["name"] for tool in provider.tools_seen[0]]
    assert tool_names == ["read_file", "find_files", "search_text"]


async def test_runtime_do_requires_latest_plan(tmp_path) -> None:
    context = ConversationContext()
    tui = FakeTui(["/do", "/exit"])
    provider = FakeProvider([])
    runtime = ArtCodeRuntime(fake_config(tmp_path / "sandbox"), provider, context, tui, plan_memory=PlanMemory())

    await runtime.run()

    assert any("请先执行 /plan" in item for item in tui.output)
    assert provider.tools_seen == []


async def test_runtime_do_uses_latest_plan_and_extra_instruction(tmp_path) -> None:
    context = ConversationContext()
    memory = PlanMemory("计划：写入 note.txt")
    tui = FakeTui(["/do 不要运行测试", "/exit"])
    provider = FakeProvider([[content_delta_event("执行完毕"), done_event()]])
    runtime = ArtCodeRuntime(fake_config(tmp_path / "sandbox"), provider, context, tui, plan_memory=memory)

    await runtime.run()

    user_message = context.export_messages()[-2]["content"]
    assert "计划：写入 note.txt" in user_message
    assert "不要运行测试" in user_message
    assert provider.tools_seen[0] is not None


async def test_runtime_executes_multiple_tools_without_confirmation(tmp_path) -> None:
    root = tmp_path / "sandbox"
    context = ConversationContext()
    tui = FakeTui(["写两个文件", "/exit"])
    provider = FakeProvider(
        [
            [
                tool_calls_event(
                    [
                        ToolCall("call_1", "write_file", '{"path":"a.txt","content":"a"}'),
                        ToolCall("call_2", "write_file", '{"path":"b.txt","content":"b"}'),
                    ]
                ),
                done_event(),
            ],
            [content_delta_event("已写入。"), done_event()],
        ]
    )
    runtime = ArtCodeRuntime(fake_config(root), provider, context, tui)

    await runtime.run()

    assert (root / "a.txt").read_text(encoding="utf-8") == "a"
    assert (root / "b.txt").read_text(encoding="utf-8") == "b"
    assert tui.confirmations_requested == 0


async def test_runtime_unknown_tool_stops_and_summarizes(tmp_path) -> None:
    context = ConversationContext()
    tui = FakeTui(["未知工具", "/exit"])
    provider = FakeProvider(
        [
            [tool_calls_event([ToolCall("call_1", "missing_tool", "{}")]), done_event()],
            [content_delta_event("未知工具。"), done_event()],
        ]
    )
    runtime = ArtCodeRuntime(fake_config(tmp_path / "sandbox"), provider, context, tui)

    await runtime.run()

    tool_message = [message for message in context.export_messages() if message.get("role") == "tool"][0]
    assert json.loads(tool_message["content"])["error_code"] == "tool_not_found"
    assert provider.tools_seen[1] is None
    assert "stopped:unknown_tool" in tui.output
