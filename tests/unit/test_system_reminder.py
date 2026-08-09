from __future__ import annotations

from pathlib import Path

from artcode.agent.modes import DO_MODE, NORMAL_AGENT_MODE, PLAN_MODE
from artcode.permissions import PermissionState
from artcode.prompting.reminder import SystemReminderBuilder, collect_runtime_reminder_context
from artcode.tools import ToolEnvironment, ToolRunContext


ALL_TOOLS = ("read_file", "write_file", "edit_file", "run_command", "find_files", "search_text")


def tool_context(root: Path, mode=NORMAL_AGENT_MODE) -> ToolRunContext:
    return ToolRunContext(
        ToolEnvironment.from_workspace(root),
        mode,
        PermissionState().snapshot(),
    )


def test_plan_mode_reminder_contains_read_only_boundaries(tmp_path) -> None:
    allowed = ("read_file", "find_files", "search_text")
    context = collect_runtime_reminder_context(PLAN_MODE, ALL_TOOLS, allowed, tool_context(tmp_path, PLAN_MODE))

    message = SystemReminderBuilder().build_message(context)

    assert message["role"] == "user"
    assert message["content"].startswith("<system-reminder>")
    assert message["content"].endswith("</system-reminder>")
    assert "plan" in message["content"]
    assert "只读规划模式" in message["content"]
    assert "read_file、find_files、search_text" in message["content"]
    assert "write_file、edit_file、run_command" in message["content"]
    assert str(tmp_path) in message["content"]
    assert "当前平台：" in message["content"]
    assert "不是用户的真实请求" in message["content"]


def test_normal_mode_reminder_lists_all_tools(tmp_path) -> None:
    context = collect_runtime_reminder_context(NORMAL_AGENT_MODE, ALL_TOOLS, ALL_TOOLS, tool_context(tmp_path))

    message = SystemReminderBuilder().build_message(context)["content"]

    assert "normal" in message
    assert "普通用户输入" in message
    assert "read_file、write_file、edit_file、run_command、find_files、search_text" in message
    assert "没有额外禁止" in message


def test_do_mode_reminder_uses_do_purpose(tmp_path) -> None:
    context = collect_runtime_reminder_context(DO_MODE, ALL_TOOLS, ALL_TOOLS, tool_context(tmp_path, DO_MODE))

    message = SystemReminderBuilder().build_message(context)["content"]

    assert "do" in message
    assert "执行最近计划" in message
