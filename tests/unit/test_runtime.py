from __future__ import annotations

import asyncio

from artcode.config import ArtCodeConfig, ThinkingConfig
from artcode.conversation import ConversationContext
from artcode.providers.events import content_delta_event, done_event
from artcode.runtime import ArtCodeRuntime


class FakeTui:
    def __init__(self, inputs: list[str]) -> None:
        self.inputs = inputs
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


class FakeProvider:
    async def stream_chat(self, messages):
        yield content_delta_event("你")
        yield content_delta_event("好")
        yield done_event()


class CancellingProvider:
    async def stream_chat(self, messages):
        raise asyncio.CancelledError
        yield done_event()


def fake_config() -> ArtCodeConfig:
    return ArtCodeConfig(
        protocol="openai",
        model="deepseek-v4-flash",
        base_url="https://api.deepseek.com",
        api_key="sk-test",
        thinking=ThinkingConfig(),
    )


async def test_runtime_adds_user_and_complete_assistant_reply() -> None:
    context = ConversationContext()
    tui = FakeTui(["你好", "/exit"])
    runtime = ArtCodeRuntime(fake_config(), FakeProvider(), context, tui)

    await runtime.run()

    messages = context.export_messages()
    assert messages[-2] == {"role": "user", "content": "你好"}
    assert messages[-1] == {"role": "assistant", "content": "你好"}


async def test_runtime_ignores_empty_input() -> None:
    context = ConversationContext()
    tui = FakeTui(["  ", "/exit"])
    runtime = ArtCodeRuntime(fake_config(), FakeProvider(), context, tui)

    await runtime.run()

    assert len(context.export_messages()) == 1


async def test_runtime_does_not_add_cancelled_assistant_reply() -> None:
    context = ConversationContext()
    tui = FakeTui(["你好", "/exit"])
    runtime = ArtCodeRuntime(fake_config(), CancellingProvider(), context, tui)

    await runtime.run()

    messages = context.export_messages()
    assert messages[-1] == {"role": "user", "content": "你好"}
    assert all(message.get("role") != "assistant" for message in messages[1:])
