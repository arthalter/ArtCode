from __future__ import annotations

import json
from pathlib import Path

from artcode.agent import PlanMemory
from artcode.config import ArtCodeConfig, ThinkingConfig
from artcode.conversation import ConversationContext
from artcode.providers.events import content_delta_event, done_event, tool_calls_event
from artcode.providers.tool_calls import ToolCall
from artcode.runtime import ArtCodeRuntime
from artcode.permissions import ApprovalChoice


class FakeTui:
    def __init__(self, inputs: list[str]) -> None:
        self.inputs = inputs
        self.output: list[str] = []

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
        raise AssertionError("Agent Loop must not ask for tool confirmation")

    async def request_approval(self, request):
        return ApprovalChoice.DENY_ONCE

    async def confirm_mcp_tool(self, preview, plan_mode: bool) -> bool:
        return False

    async def confirm_unsandboxed(self) -> bool:
        return False

    def show_tool_result_summary(self, result) -> None:
        self.output.append(f"tool:{result.tool_name}:{result.status}:{result.error_code}")

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

    def clear_screen(self) -> None:
        self.output.append("clear")

    def show_runtime_status(self, snapshot) -> None:
        self.output.append("status")

    def show_context_status(self, payload: dict) -> None:
        self.output.append("context")

    def show_persistence_status(self, payload: dict) -> None:
        self.output.append("persistence")


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


def config_for(allowed_dir: Path) -> ArtCodeConfig:
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


async def run_runtime(tmp_path, inputs: list[str], responses: list[list[dict]], memory: PlanMemory | None = None):
    allowed_dir = tmp_path / "sandbox"
    context = ConversationContext()
    provider = FakeProvider(responses)
    tui = FakeTui(inputs)
    runtime = ArtCodeRuntime(
        config_for(allowed_dir),
        provider,
        context,
        tui,
        plan_memory=memory,
    )

    await runtime.run()

    return allowed_dir, provider, context, tui, runtime.plan_memory


async def test_agent_loop_reads_writes_verifies_and_summarizes(tmp_path) -> None:
    allowed_dir = tmp_path / "sandbox"
    allowed_dir.mkdir()
    (allowed_dir / "source.txt").write_text("hello", encoding="utf-8")
    responses = [
        [tool_calls_event([ToolCall("call_1", "read_file", '{"path":"source.txt"}')]), done_event()],
        [tool_calls_event([ToolCall("call_2", "write_file", '{"path":"result.txt","content":"hello world"}')]), done_event()],
        [tool_calls_event([ToolCall("call_3", "read_file", '{"path":"result.txt"}')]), done_event()],
        [content_delta_event("已读取、写入并验证。"), done_event()],
    ]

    allowed_dir, provider, context, _, _ = await run_runtime(tmp_path, ["处理文件", "/exit"], responses)

    assert (allowed_dir / "result.txt").read_text(encoding="utf-8") == "hello world"
    assert [payload["tool_name"] for payload in tool_payloads(context)] == ["read_file", "write_file", "read_file"]
    assert context.export_messages()[-1]["content"] == "已读取、写入并验证。"
    assert all(request[-1]["content"].startswith("<system-reminder>") for request in provider.messages_seen)
    assert not any(message.get("content", "").startswith("<system-reminder>") for message in context.export_messages())


async def test_plan_then_do_executes_latest_plan(tmp_path) -> None:
    responses = [
        [content_delta_event("计划：写入 planned.txt"), done_event()],
        [tool_calls_event([ToolCall("call_1", "write_file", '{"path":"planned.txt","content":"ok"}')]), done_event()],
        [content_delta_event("计划已执行。"), done_event()],
    ]

    allowed_dir, provider, context, _, memory = await run_runtime(
        tmp_path,
        ["/plan 写入 planned.txt", "/do", "/exit"],
        responses,
        PlanMemory(),
    )

    assert memory.get() == "计划：写入 planned.txt"
    assert (allowed_dir / "planned.txt").read_text(encoding="utf-8") == "ok"
    assert [tool["function"]["name"] for tool in provider.tools_seen[0]] == ["read_file", "find_files", "search_text"]
    assert "write_file、edit_file、run_command" in provider.messages_seen[0][-1]["content"]
    assert context.export_messages()[-1]["content"] == "计划已执行。"


async def test_multiple_read_only_tools_preserve_result_order(tmp_path) -> None:
    allowed_dir = tmp_path / "sandbox"
    allowed_dir.mkdir()
    (allowed_dir / "a.txt").write_text("alpha", encoding="utf-8")
    responses = [
        [
            tool_calls_event(
                [
                    ToolCall("call_1", "read_file", '{"path":"a.txt"}'),
                    ToolCall("call_2", "find_files", '{"pattern":"*.txt"}'),
                ]
            ),
            done_event(),
        ],
        [content_delta_event("完成。"), done_event()],
    ]

    _, _, context, tui, _ = await run_runtime(tmp_path, ["读和找", "/exit"], responses)

    tool_messages = [message for message in context.export_messages() if message.get("role") == "tool"]
    assert [message["tool_call_id"] for message in tool_messages] == ["call_1", "call_2"]
    assert "batch:1:read_only:2" in tui.output


async def test_unknown_tool_executes_no_tools_and_summarizes(tmp_path) -> None:
    responses = [
        [
            tool_calls_event(
                [
                    ToolCall("call_1", "missing_tool", "{}"),
                    ToolCall("call_2", "write_file", '{"path":"should_not_exist.txt","content":"no"}'),
                ]
            ),
            done_event(),
        ],
        [content_delta_event("未知工具，已停止。"), done_event()],
    ]

    allowed_dir, _, context, tui, _ = await run_runtime(tmp_path, ["未知工具", "/exit"], responses)

    assert not (allowed_dir / "should_not_exist.txt").exists()
    payloads = tool_payloads(context)
    tool_messages = [message for message in context.export_messages() if message.get("role") == "tool"]
    assert [message["tool_call_id"] for message in tool_messages] == ["call_1", "call_2"]
    assert [payload["error_code"] for payload in payloads] == ["tool_not_found", "tool_execution_blocked"]
    assert "stopped:unknown_tool" in tui.output
    assert context.export_messages()[-1]["content"] == "未知工具，已停止。"
