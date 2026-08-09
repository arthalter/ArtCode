from __future__ import annotations

import json
from pathlib import Path

from artcode.agent import PlanMemory, TokenUsage
from artcode.config import ArtCodeConfig, ThinkingConfig
from artcode.conversation import ConversationContext
from artcode.providers.events import (
    content_delta_event,
    done_event,
    token_usage_event,
    tool_calls_event,
)
from artcode.providers.tool_calls import ToolCall
from tests.runtime_factory import build_test_runtime as ArtCodeRuntime
from artcode.context_management import ContextManager, ContextSummarizer
from artcode.context_management.retention import RetentionPlanner
from artcode.context_management.summarizer import SUMMARY_TITLES, VERBATIM_PLACEHOLDER
from artcode.errors import NetworkError
from artcode.persistence import PersistenceCoordinator, SessionSelection
from artcode.permissions import ApprovalChoice, PermissionMode, ShellPolicy
from artcode.workspace import ArtCodePaths, Workspace


class FakeTui:
    def __init__(self, inputs: list[str]) -> None:
        self.inputs = inputs
        self.output: list[str] = []
        self.confirmations_requested = 0
        self.display_modes = []
        self.current_display_mode = None
        self.clear_count = 0
        self.statuses = []

    def show_startup(self, status) -> None:
        self.output.append("startup")

    def show_mcp_startup(self, report) -> None:
        self.output.append("mcp")

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

    async def request_approval(self, request):
        return ApprovalChoice.DENY_ONCE

    async def confirm_mcp_tool(self, preview, plan_mode: bool) -> bool:
        self.confirmations_requested += 1
        return False

    async def confirm_unsandboxed(self) -> bool:
        return False

    def show_tool_result_summary(self, result) -> None:
        self.output.append(f"tool:{result.status}:{result.error_code}")

    def show_agent_iteration(self, current: int, maximum: int | None) -> None:
        suffix = str(current) if maximum is None else f"{current}/{maximum}"
        self.output.append(f"iteration:{suffix}")

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
        self.output.append(f"usage:{total_tokens}:{cached_tokens}:{cache_miss_tokens}")

    def show_agent_stopped(self, reason: str, message: str = "") -> None:
        self.output.append(f"stopped:{reason}")

    def show_context_status(self, payload: dict) -> None:
        self.output.append(f"context:{payload['trigger']}:{payload['status']}")

    def show_persistence_status(self, payload: dict) -> None:
        self.output.append(f"persistence:{payload['kind']}:{payload['status']}")

    def set_display_mode(self, mode) -> None:
        self.current_display_mode = mode
        self.display_modes.append(mode)

    def clear_screen(self) -> None:
        self.clear_count += 1

    def show_runtime_status(self, snapshot) -> None:
        self.statuses.append(snapshot)


class FakeProvider:
    def __init__(self, responses: list[list[dict]]) -> None:
        self.responses = responses
        self.tools_seen: list[list[dict] | None] = []
        self.messages_seen: list[list[dict]] = []

    async def stream_chat(self, messages, tools=None, *, options=None):
        self.messages_seen.append(list(messages))
        self.tools_seen.append(tools)
        for event in self.responses.pop(0):
            yield event


class FailingProvider:
    async def stream_chat(self, messages, tools=None, *, options=None):
        raise NetworkError("模拟网络失败")
        yield


def valid_summary() -> str:
    sections = []
    for index, title in enumerate(SUMMARY_TITLES, start=1):
        body = VERBATIM_PLACEHOLDER if index == 6 else f"内容 {index}"
        sections.append(f"## {index}. {title}\n{body}")
    return "<analysis>draft</analysis><summary>" + "\n\n".join(sections) + "</summary>"


def fake_config(root: Path) -> ArtCodeConfig:
    root.mkdir(exist_ok=True)
    return ArtCodeConfig(
        protocol="openai",
        model="deepseek-v4-flash",
        base_url="https://api.deepseek.com",
        api_key="sk-test",
        thinking=ThinkingConfig(),
        workspace=root,
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
    assert "iteration:1" in tui.output
    assert "stopped:natural" in tui.output


async def test_runtime_ignores_empty_input(tmp_path) -> None:
    context = ConversationContext()
    tui = FakeTui(["  ", "/exit"])
    provider = FakeProvider([])
    runtime = ArtCodeRuntime(fake_config(tmp_path / "sandbox"), provider, context, tui)

    await runtime.run()

    assert len(context.export_messages()) == 1


async def test_runtime_keeps_sentence_slash_on_agent_path(tmp_path) -> None:
    context = ConversationContext()
    tui = FakeTui(["请解释 /help", "/exit"])
    provider = FakeProvider([[content_delta_event("解释完成"), done_event()]])
    runtime = ArtCodeRuntime(fake_config(tmp_path / "sandbox"), provider, context, tui)

    await runtime.run()

    assert provider.messages_seen
    assert context.export_messages()[-2]["content"] == "请解释 /help"


async def test_runtime_unknown_multiline_command_never_enters_agent(tmp_path) -> None:
    context = ConversationContext()
    before = context.export_messages()
    tui = FakeTui([" /Unknown\n不要发送", "/exit"])
    provider = FakeProvider([])
    runtime = ArtCodeRuntime(fake_config(tmp_path / "sandbox"), provider, context, tui)

    await runtime.run()

    assert provider.messages_seen == []
    assert context.export_messages() == before
    assert any("/Unknown" in item and "/help" in item for item in tui.output)


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
    assert [mode.value for mode in tui.display_modes] == ["PLAN", "DEFAULT"]
    assert tui.current_display_mode.value == "DEFAULT"


async def test_runtime_plan_without_task_preserves_existing_plan(tmp_path) -> None:
    context = ConversationContext()
    memory = PlanMemory("原计划")
    tui = FakeTui(["/plan", "/exit"])
    provider = FakeProvider([])
    runtime = ArtCodeRuntime(
        fake_config(tmp_path / "sandbox"),
        provider,
        context,
        tui,
        plan_memory=memory,
    )

    await runtime.run()

    assert memory.get() == "原计划"
    assert provider.messages_seen == []


async def test_runtime_multiline_plan_preserves_complete_task(tmp_path) -> None:
    context = ConversationContext()
    tui = FakeTui(["/plan 第一行\n第二行", "/exit"])
    provider = FakeProvider([[content_delta_event("计划"), done_event()]])
    runtime = ArtCodeRuntime(fake_config(tmp_path / "sandbox"), provider, context, tui)

    await runtime.run()

    user_messages = [item for item in context.export_messages() if item.get("role") == "user"]
    assert user_messages[-1]["content"] == "第一行\n第二行"
    assert all("/plan" not in str(item.get("content", "")) for item in user_messages)


async def test_runtime_restores_default_mode_after_plan_failure(tmp_path) -> None:
    context = ConversationContext()
    tui = FakeTui(["/plan 测试异常", "/exit"])
    runtime = ArtCodeRuntime(
        fake_config(tmp_path / "sandbox"),
        FailingProvider(),
        context,
        tui,
    )

    await runtime.run()

    assert [mode.value for mode in tui.display_modes] == ["PLAN", "DEFAULT"]
    assert tui.current_display_mode.value == "DEFAULT"
    assert "stopped:stream_error" in tui.output


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


async def test_runtime_compact_does_not_append_command_as_user_message(tmp_path) -> None:
    context = ConversationContext("system")
    for index in range(12):
        if index % 2 == 0:
            context.append_user(f"old {index}")
        else:
            context.append_assistant("x" * 100)
    user_count_before = sum(message["role"] == "user" for message in context.export_messages())
    tui = FakeTui(["/compact", "/exit"])
    provider = FakeProvider([[content_delta_event(valid_summary()), done_event()]])
    context_manager = ContextManager(
        fake_config(tmp_path / "sandbox").context,
        ContextSummarizer(provider, context),
        retention_planner=RetentionPlanner(recent_token_budget=50, minimum_messages=3),
    )
    runtime = ArtCodeRuntime(
        fake_config(tmp_path / "sandbox-2"),
        provider,
        context,
        tui,
        context_manager=context_manager,
    )

    await runtime.run()

    assert "context:manual:success" in tui.output
    assert all(message.get("content") != "/compact" for message in context.export_messages())
    assert user_count_before == 6
    assert len(provider.messages_seen) == 1


async def test_runtime_clear_only_changes_visible_terminal(tmp_path) -> None:
    context = ConversationContext()
    context.append_user("保留对话")
    memory = PlanMemory("保留计划")
    tui = FakeTui(["/clear", "/exit"])
    provider = FakeProvider([])
    runtime = ArtCodeRuntime(
        fake_config(tmp_path / "sandbox"),
        provider,
        context,
        tui,
        plan_memory=memory,
    )
    runtime.state.record_usage(TokenUsage(total_tokens=99))
    runtime.state.permission.mode = PermissionMode.EDIT
    runtime.state.permission.shell_policy = ShellPolicy.SANDBOX_ASK
    before = context.export_messages()

    await runtime.run()

    assert tui.clear_count == 1
    assert context.export_messages() == before
    assert memory.get() == "保留计划"
    assert runtime.get_token_usage() == TokenUsage(total_tokens=99)
    assert runtime.state.permission.mode is PermissionMode.EDIT
    assert runtime.state.permission.shell_policy is ShellPolicy.SANDBOX_ASK
    assert provider.messages_seen == []


async def test_runtime_status_is_local_and_reports_missing_or_real_usage(tmp_path) -> None:
    context = ConversationContext()
    tui = FakeTui(
        ["/status", "普通消息", "/status", "第二条消息", "/status", "/exit"]
    )
    provider = FakeProvider(
        [
            [token_usage_event(10, 4, 14, cached_tokens=3, cache_miss_tokens=7), done_event()],
            [token_usage_event(20, 5, 25, cached_tokens=8, cache_miss_tokens=12), done_event()],
        ]
    )
    runtime = ArtCodeRuntime(fake_config(tmp_path / "sandbox"), provider, context, tui)

    await runtime.run()

    assert len(provider.messages_seen) == 2
    assert len(tui.statuses) == 3
    assert tui.statuses[0].last_token_usage is None
    assert tui.statuses[0].estimated_context_tokens is None
    assert tui.statuses[1].last_token_usage == TokenUsage(10, 4, 14, 3, 7)
    assert tui.statuses[1].model == "deepseek-v4-flash"
    assert tui.statuses[1].permission_mode == "default"
    assert tui.statuses[1].shell_policy == "auto"
    assert tui.statuses[2].last_token_usage == TokenUsage(20, 5, 25, 8, 12)


async def test_all_non_ai_builtin_commands_do_not_call_provider(tmp_path) -> None:
    context = ConversationContext()
    tui = FakeTui(
        [
            "/help",
            "/permission",
            "/sandbox",
            "/sessions",
            "/memory",
            "/clear",
            "/status",
            "/exit",
        ]
    )
    provider = FakeProvider([])
    runtime = ArtCodeRuntime(fake_config(tmp_path / "sandbox"), provider, context, tui)

    await runtime.run()

    assert provider.messages_seen == []
    assert all(not str(item.get("content", "")).startswith("/") for item in context.export_messages())


async def test_runtime_persistence_commands_show_metadata_without_becoming_messages(tmp_path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    workspace = Workspace.from_path(root)
    provider = FakeProvider([])
    persistence = PersistenceCoordinator.start(
        ArtCodePaths.create(tmp_path / "home"),
        workspace,
        provider,
        SessionSelection.new(),
    )
    tui = FakeTui(["/sessions", "/memory", "/exit"])
    runtime = ArtCodeRuntime(
        fake_config(root),
        provider,
        persistence.conversation,
        tui,
        workspace=workspace,
        plan_memory=persistence.plan_memory,
        persistence=persistence,
    )
    try:
        await runtime.run()
        output = "\n".join(tui.output)
        assert persistence.status.session_id in output
        assert "用户级记忆" in output
        assert "项目级记忆" in output
        assert "superseded=0" in output
        assert len(persistence.conversation.export_messages()) == 1
    finally:
        await persistence.close()
