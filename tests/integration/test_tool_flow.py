from __future__ import annotations

import json

from artcode.config import ArtCodeConfig, ThinkingConfig
from artcode.conversation import ConversationContext
from artcode.permissions import PermissionState
from artcode.providers.events import content_delta_event, done_event, tool_calls_event
from artcode.providers.tool_calls import ToolCall
from artcode.runtime import ArtCodeRuntime
from artcode.tools import AllowedPathPolicy, ToolExecutionContext


class FakeTui:
    def __init__(self, user_input: str, confirmations: list[bool] | None = None) -> None:
        self.output: list[str] = []
        self.inputs = [user_input, "/exit"]
        self.confirmations = confirmations or []
        self.confirmations_requested = 0

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
        self.confirmations_requested += 1
        return self.confirmations.pop(0)

    def show_tool_result_summary(self, result) -> None:
        self.output.append(f"{result.status}:{result.error_code}")

    def show_agent_iteration(self, current: int, maximum: int) -> None:
        self.output.append(f"iteration:{current}/{maximum}")

    def show_tool_calls_received(self, count: int) -> None:
        self.output.append(f"tool_calls:{count}")

    def show_tool_batch_started(self, batch_index: int, safety: str, count: int) -> None:
        self.output.append(f"batch:{batch_index}:{safety}:{count}")

    def show_token_usage(
        self,
        prompt_tokens=None,
        completion_tokens=None,
        total_tokens=None,
        cached_tokens=None,
        cache_miss_tokens=None,
    ) -> None:
        self.output.append(f"usage:{total_tokens}")

    def show_agent_stopped(self, reason: str, message: str = "") -> None:
        self.output.append(f"stopped:{reason}")

    def set_display_mode(self, mode) -> None:
        self.output.append(f"mode:{mode.value}")


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
        workspace=allowed_dir,
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
        permission_state=(
            PermissionState(shell_policy=tool_context.shell_policy)
            if tool_context is not None
            else None
        ),
    )

    await runtime.run()

    return allowed_dir, provider, context, tui


async def test_tool_write_flow_auto_executes_and_summarizes(tmp_path) -> None:
    allowed_dir, provider, context, tui = await run_flow(
        tmp_path,
        "请写入 note.txt",
        [ToolCall("call_1", "write_file", '{"path":"note.txt","content":"hello from tool"}')],
        "文件已写入。",
    )

    assert (allowed_dir / "note.txt").read_text(encoding="utf-8") == "hello from tool"
    assert tui.confirmations_requested == 0
    assert provider.tools_seen[0] is not None
    assert provider.tools_seen[1] is not None
    assert context.export_messages()[-1] == {"role": "assistant", "content": "文件已写入。"}


async def test_outside_read_flow_returns_boundary_error_and_summary(tmp_path) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")

    _, _, context, _ = await run_flow(
        tmp_path,
        "读取外部文件",
        [ToolCall("call_1", "read_file", json.dumps({"path": str(outside)}))],
        "无法读取，路径越界。",
    )

    payload = tool_payloads(context)[0]
    assert payload["error_code"] == "path_outside_allowed_dirs"
    assert context.export_messages()[-1]["content"] == "无法读取，路径越界。"


async def test_side_effect_tool_does_not_request_confirmation(tmp_path) -> None:
    allowed_dir, _, context, tui = await run_flow(
        tmp_path,
        "请写入 note.txt",
        [ToolCall("call_1", "write_file", '{"path":"note.txt","content":"hello"}')],
        "已自动执行。",
    )

    assert (allowed_dir / "note.txt").read_text(encoding="utf-8") == "hello"
    assert tui.confirmations_requested == 0
    assert tool_payloads(context)[0]["ok"] is True
    assert context.export_messages()[-1]["content"] == "已自动执行。"


async def test_multiple_tool_calls_flow_executes_all_and_summarizes(tmp_path) -> None:
    allowed_dir, _, context, tui = await run_flow(
        tmp_path,
        "多个工具",
        [
            ToolCall("call_1", "write_file", '{"path":"a.txt","content":"a"}'),
            ToolCall("call_2", "write_file", '{"path":"b.txt","content":"b"}'),
        ],
        "两个文件都写好了。",
    )

    assert (allowed_dir / "a.txt").read_text(encoding="utf-8") == "a"
    assert (allowed_dir / "b.txt").read_text(encoding="utf-8") == "b"
    payloads = tool_payloads(context)
    assert [payload["ok"] for payload in payloads] == [True, True]
    assert "tool_calls:2" in tui.output
    assert context.export_messages()[-1]["content"] == "两个文件都写好了。"


async def test_command_timeout_flow_returns_error_and_summary(tmp_path) -> None:
    allowed_dir = tmp_path / "sandbox"
    allowed_dir.mkdir()
    tool_context = ToolExecutionContext(
        AllowedPathPolicy((allowed_dir,)),
        command_timeout_seconds=0.05,
        default_cwd=allowed_dir,
    )
    _, _, context, _ = await run_flow(
        tmp_path,
        "执行慢命令",
        [ToolCall("call_1", "run_command", '{"command":"sleep 1"}')],
        "命令执行超时。",
        tool_context=tool_context,
    )

    assert tool_payloads(context)[0]["error_code"] == "command_timeout"
    assert context.export_messages()[-1]["content"] == "命令执行超时。"
