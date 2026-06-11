from __future__ import annotations

import asyncio
import json
from pathlib import Path

from artcode.config import ArtCodeConfig, ThinkingConfig, ToolConfig
from artcode.conversation import ConversationContext
from artcode.providers.events import content_delta_event, done_event, tool_calls_event
from artcode.providers.tool_calls import ToolCall
from artcode.runtime import ArtCodeRuntime


class FakeTui:
    def __init__(self, inputs: list[str], confirmations: list[bool] | None = None) -> None:
        self.inputs = inputs
        self.confirmations = confirmations or []
        self.output: list[str] = []

    def show_startup(self, status) -> None:
        self.output.append("startup")

    async def read_input(self, model: str) -> str:
        return self.inputs.pop(0)

    def show_help(self, message: str) -> None:
        self.output.append(message)

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
        return self.confirmations.pop(0)

    def show_tool_result_summary(self, result) -> None:
        self.output.append(f"tool:{result.status}:{result.error_code}")


class FakeProvider:
    def __init__(self, responses: list[list[dict]]) -> None:
        self.responses = responses
        self.tools_seen: list[list[dict] | None] = []

    async def stream_chat(self, messages, tools=None):
        self.tools_seen.append(tools)
        for event in self.responses.pop(0):
            yield event


class CancellingProvider:
    async def stream_chat(self, messages, tools=None):
        raise asyncio.CancelledError
        yield done_event()


class CancelOnSecondProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def stream_chat(self, messages, tools=None):
        self.calls += 1
        if self.calls == 1:
            yield tool_calls_event([ToolCall("call_1", "write_file", '{"path":"note.txt","content":"hello"}')])
            yield done_event()
            return
        raise asyncio.CancelledError
        yield done_event()


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


async def test_runtime_adds_user_and_complete_assistant_reply(tmp_path) -> None:
    context = ConversationContext()
    tui = FakeTui(["你好", "/exit"])
    provider = FakeProvider([[content_delta_event("你"), content_delta_event("好"), done_event()]])
    runtime = ArtCodeRuntime(fake_config(tmp_path / "sandbox"), provider, context, tui)

    await runtime.run()

    messages = context.export_messages()
    assert messages[-2] == {"role": "user", "content": "你好"}
    assert messages[-1] == {"role": "assistant", "content": "你好"}
    assert provider.tools_seen[0] is not None


async def test_runtime_ignores_empty_input(tmp_path) -> None:
    context = ConversationContext()
    tui = FakeTui(["  ", "/exit"])
    provider = FakeProvider([])
    runtime = ArtCodeRuntime(fake_config(tmp_path / "sandbox"), provider, context, tui)

    await runtime.run()

    assert len(context.export_messages()) == 1


async def test_runtime_does_not_add_cancelled_assistant_reply(tmp_path) -> None:
    context = ConversationContext()
    tui = FakeTui(["你好", "/exit"])
    runtime = ArtCodeRuntime(fake_config(tmp_path / "sandbox"), CancellingProvider(), context, tui)

    await runtime.run()

    messages = context.export_messages()
    assert messages[-1] == {"role": "user", "content": "你好"}
    assert all(message.get("role") != "assistant" for message in messages[1:])


async def test_runtime_executes_single_tool_and_summarizes(tmp_path) -> None:
    root = tmp_path / "sandbox"
    context = ConversationContext()
    tui = FakeTui(["写文件", "/exit"], confirmations=[True])
    provider = FakeProvider(
        [
            [tool_calls_event([ToolCall("call_1", "write_file", '{"path":"note.txt","content":"hello"}')]), done_event()],
            [content_delta_event("已写入。"), done_event()],
        ]
    )
    runtime = ArtCodeRuntime(fake_config(root), provider, context, tui)

    await runtime.run()

    assert (root / "note.txt").read_text(encoding="utf-8") == "hello"
    messages = context.export_messages()
    assert any(message.get("role") == "tool" for message in messages)
    assert messages[-1] == {"role": "assistant", "content": "已写入。"}
    assert provider.tools_seen[0] is not None
    assert provider.tools_seen[1] is None


async def test_runtime_user_denies_side_effect_tool(tmp_path) -> None:
    root = tmp_path / "sandbox"
    context = ConversationContext()
    tui = FakeTui(["写文件", "/exit"], confirmations=[False])
    provider = FakeProvider(
        [
            [tool_calls_event([ToolCall("call_1", "write_file", '{"path":"note.txt","content":"hello"}')]), done_event()],
            [content_delta_event("用户拒绝。"), done_event()],
        ]
    )
    runtime = ArtCodeRuntime(fake_config(root), provider, context, tui)

    await runtime.run()

    assert not (root / "note.txt").exists()
    tool_message = [message for message in context.export_messages() if message.get("role") == "tool"][0]
    payload = json.loads(tool_message["content"])
    assert payload["error_code"] == "user_denied"


async def test_runtime_invalid_json_arguments_are_returned_to_model(tmp_path) -> None:
    context = ConversationContext()
    tui = FakeTui(["读文件", "/exit"])
    provider = FakeProvider(
        [
            [tool_calls_event([ToolCall("call_1", "read_file", "{")]), done_event()],
            [content_delta_event("参数错误。"), done_event()],
        ]
    )
    runtime = ArtCodeRuntime(fake_config(tmp_path / "sandbox"), provider, context, tui)

    await runtime.run()

    tool_message = [message for message in context.export_messages() if message.get("role") == "tool"][0]
    payload = json.loads(tool_message["content"])
    assert payload["error_code"] == "invalid_arguments"


async def test_runtime_unknown_tool_is_returned_to_model(tmp_path) -> None:
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
    payload = json.loads(tool_message["content"])
    assert payload["error_code"] == "tool_not_found"


async def test_runtime_multiple_tool_calls_are_not_executed(tmp_path) -> None:
    root = tmp_path / "sandbox"
    context = ConversationContext()
    tui = FakeTui(["多个工具", "/exit"])
    calls = [
        ToolCall("call_1", "write_file", '{"path":"a.txt","content":"a"}'),
        ToolCall("call_2", "write_file", '{"path":"b.txt","content":"b"}'),
    ]
    provider = FakeProvider(
        [
            [tool_calls_event(calls), done_event()],
            [content_delta_event("只允许一个工具。"), done_event()],
        ]
    )
    runtime = ArtCodeRuntime(fake_config(root), provider, context, tui)

    await runtime.run()

    assert not (root / "a.txt").exists()
    assert not (root / "b.txt").exists()
    tool_messages = [message for message in context.export_messages() if message.get("role") == "tool"]
    assert [message["tool_call_id"] for message in tool_messages] == ["call_1", "call_2"]
    payloads = [json.loads(message["content"]) for message in tool_messages]
    assert all(payload["error_code"] == "too_many_tool_calls" for payload in payloads)


async def test_runtime_does_not_add_cancelled_final_summary(tmp_path) -> None:
    root = tmp_path / "sandbox"
    context = ConversationContext()
    tui = FakeTui(["写文件", "/exit"], confirmations=[True])
    runtime = ArtCodeRuntime(fake_config(root), CancelOnSecondProvider(), context, tui)

    await runtime.run()

    messages = context.export_messages()
    assert any(message.get("role") == "tool" for message in messages)
    assert messages[-1]["role"] == "tool"
