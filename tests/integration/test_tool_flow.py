from __future__ import annotations

import json

from artcode.config import ArtCodeConfig, ThinkingConfig, ToolConfig
from artcode.conversation import ConversationContext
from artcode.providers.events import content_delta_event, done_event, tool_calls_event
from artcode.providers.tool_calls import ToolCall
from artcode.runtime import ArtCodeRuntime
from artcode.tools import AllowedPathPolicy, ToolExecutionContext


class FakeTui:
    def __init__(self, user_input: str, confirmations: list[bool] | None = None) -> None:
        self.output: list[str] = []
        self.inputs = [user_input, "/exit"]
        self.confirmations = confirmations or []

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
        self.output.append(preview.tool_name)

    async def confirm_tool_execution(self, preview) -> bool:
        return self.confirmations.pop(0)

    def show_tool_result_summary(self, result) -> None:
        self.output.append(f"{result.status}:{result.error_code}")


class FakeProvider:
    def __init__(self, tool_calls: list[ToolCall], final_reply: str) -> None:
        self.tool_calls = tool_calls
        self.final_reply = final_reply
        self.calls = 0
        self.tools_seen: list[list[dict] | None] = []

    async def stream_chat(self, messages, tools=None):
        self.calls += 1
        self.tools_seen.append(tools)
        if self.calls == 1:
            yield tool_calls_event(self.tool_calls)
            yield done_event()
            return
        yield content_delta_event(self.final_reply)
        yield done_event()


def config_for(allowed_dir) -> ArtCodeConfig:
    allowed_dir.mkdir(exist_ok=True)
    return ArtCodeConfig(
        protocol="openai",
        model="fake-model",
        base_url="https://example.invalid",
        api_key="sk-test",
        thinking=ThinkingConfig(),
        tools=ToolConfig((allowed_dir,)),
    )


def tool_payloads(context: ConversationContext) -> list[dict]:
    return [
        json.loads(message["content"])
        for message in context.export_messages()
        if message.get("role") == "tool"
    ]


async def run_flow(tmp_path, user_input: str, tool_calls: list[ToolCall], final_reply: str, confirmations=None, tool_context=None):
    allowed_dir = tmp_path / "sandbox"
    config = config_for(allowed_dir)
    provider = FakeProvider(tool_calls, final_reply)
    context = ConversationContext()
    tui = FakeTui(user_input, confirmations)
    runtime = ArtCodeRuntime(
        config=config,
        provider=provider,
        conversation=context,
        tui=tui,
        tool_context=tool_context,
    )

    await runtime.run()

    return allowed_dir, provider, context


async def test_tool_write_flow_with_confirmation_and_summary(tmp_path) -> None:
    allowed_dir, provider, context = await run_flow(
        tmp_path,
        "请写入 note.txt",
        [ToolCall("call_1", "write_file", '{"path":"note.txt","content":"hello from tool"}')],
        "文件已写入。",
        confirmations=[True],
    )

    assert (allowed_dir / "note.txt").read_text(encoding="utf-8") == "hello from tool"
    assert provider.tools_seen[0] is not None
    assert provider.tools_seen[1] is None
    assert context.export_messages()[-1] == {"role": "assistant", "content": "文件已写入。"}


async def test_outside_read_flow_returns_boundary_error_and_summary(tmp_path) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")

    _, _, context = await run_flow(
        tmp_path,
        "读取外部文件",
        [ToolCall("call_1", "read_file", json.dumps({"path": str(outside)}))],
        "无法读取，路径越界。",
    )

    payload = tool_payloads(context)[0]
    assert payload["error_code"] == "path_outside_allowed_dirs"
    assert context.export_messages()[-1]["content"] == "无法读取，路径越界。"


async def test_user_denies_write_flow_and_file_is_not_created(tmp_path) -> None:
    allowed_dir, _, context = await run_flow(
        tmp_path,
        "请写入 note.txt",
        [ToolCall("call_1", "write_file", '{"path":"note.txt","content":"hello"}')],
        "操作已被用户拒绝。",
        confirmations=[False],
    )

    assert not (allowed_dir / "note.txt").exists()
    assert tool_payloads(context)[0]["error_code"] == "user_denied"
    assert context.export_messages()[-1]["content"] == "操作已被用户拒绝。"


async def test_multiple_tool_calls_flow_executes_none_and_summarizes(tmp_path) -> None:
    allowed_dir, _, context = await run_flow(
        tmp_path,
        "多个工具",
        [
            ToolCall("call_1", "write_file", '{"path":"a.txt","content":"a"}'),
            ToolCall("call_2", "write_file", '{"path":"b.txt","content":"b"}'),
        ],
        "本章只支持单工具调用。",
    )

    assert not (allowed_dir / "a.txt").exists()
    assert not (allowed_dir / "b.txt").exists()
    payloads = tool_payloads(context)
    assert [payload["error_code"] for payload in payloads] == ["too_many_tool_calls", "too_many_tool_calls"]
    assert context.export_messages()[-1]["content"] == "本章只支持单工具调用。"


async def test_command_timeout_flow_returns_error_and_summary(tmp_path) -> None:
    allowed_dir = tmp_path / "sandbox"
    allowed_dir.mkdir()
    tool_context = ToolExecutionContext(
        AllowedPathPolicy((allowed_dir,)),
        command_timeout_seconds=0.05,
        default_cwd=allowed_dir,
    )
    _, _, context = await run_flow(
        tmp_path,
        "执行慢命令",
        [ToolCall("call_1", "run_command", '{"command":"sleep 1"}')],
        "命令执行超时。",
        confirmations=[True],
        tool_context=tool_context,
    )

    assert tool_payloads(context)[0]["error_code"] == "command_timeout"
    assert context.export_messages()[-1]["content"] == "命令执行超时。"
