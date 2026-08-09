from __future__ import annotations

import platform as platform_lib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from artcode.tools import ToolExecutionContext, ToolRunContext

if TYPE_CHECKING:
    from artcode.agent.modes import AgentMode


@dataclass(frozen=True)
class ReminderContext:
    mode_name: str
    mode_purpose: str
    allowed_tool_names: tuple[str, ...]
    blocked_tool_names: tuple[str, ...]
    cwd: Path
    platform: str
    workspace: Path | None = None
    permission_mode: str = "default"
    shell_policy: str = "off"


class SystemReminderBuilder:
    def build_message(self, context: ReminderContext) -> dict[str, str]:
        lines = [
            "<system-reminder>",
            "这是系统级补充约束，不是用户的真实请求；不要向用户解释本标签，也不要围绕本提醒作答。",
            f"当前运行模式：{context.mode_name}。",
            f"模式说明：{context.mode_purpose}",
            f"本轮允许工具：{_join_names(context.allowed_tool_names)}。",
            _blocked_tools_line(context.blocked_tool_names),
            f"当前工作目录：{context.cwd}",
            f"当前平台：{context.platform}",
            f"Workspace：{context.workspace or context.cwd}",
            f"权限模式：{context.permission_mode}。",
            f"Shell 策略：{context.shell_policy}。",
            "硬安全边界：Plan 只读、Workspace 外路径、敏感路径和危险命令不可通过规则或人工授权解除。",
            "工具可能自动执行、请求授权或被拒绝；本提醒仅解释边界，执行层仍会强制检查。",
            "</system-reminder>",
        ]
        return {"role": "user", "content": "\n".join(lines)}


def build_resume_reminder_message() -> dict[str, str]:
    """Build the request-only reminder used after a long session gap."""
    return {
        "role": "user",
        "content": (
            "<system-reminder>\n"
            "恢复会话距最后有效消息已超过 24 小时。文件、依赖、进程和运行环境可能已变化；"
            "继续任务前应重新读取或验证相关现状，不要仅依据旧会话假设。\n"
            "</system-reminder>"
        ),
    }


def collect_runtime_reminder_context(
    mode: AgentMode,
    all_tool_names: tuple[str, ...],
    allowed_tool_names: tuple[str, ...],
    tool_context: ToolExecutionContext | ToolRunContext,
) -> ReminderContext:
    allowed = tuple(name for name in all_tool_names if name in set(allowed_tool_names))
    blocked = tuple(name for name in all_tool_names if name not in set(allowed_tool_names))
    state = tool_context.permission_state
    return ReminderContext(
        mode_name=mode.name,
        mode_purpose=mode.purpose,
        allowed_tool_names=allowed,
        blocked_tool_names=blocked,
        cwd=tool_context.default_cwd or Path.cwd(),
        platform=_current_platform(),
        workspace=tool_context.default_cwd,
        permission_mode=state.mode.value if state is not None else "default",
        shell_policy=state.shell_policy.value if state is not None else tool_context.shell_policy.value,
    )


def _current_platform() -> str:
    system = platform_lib.system()
    machine = platform_lib.machine()
    if system == "Darwin":
        system = "macOS"
    return " ".join(part for part in (system, machine) if part)


def _join_names(names: tuple[str, ...]) -> str:
    return "、".join(names) if names else "无"


def _blocked_tools_line(names: tuple[str, ...]) -> str:
    if names:
        return f"本轮禁止或不可用工具：{_join_names(names)}。"
    return "本轮没有额外禁止的默认工具；仍需遵守安全边界和谨慎使用有副作用工具。"
