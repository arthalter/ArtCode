from __future__ import annotations

import platform as platform_lib
from dataclasses import dataclass
from pathlib import Path

from artcode.agent.modes import AgentMode
from artcode.tools import ToolExecutionContext


@dataclass(frozen=True)
class ReminderContext:
    mode_name: str
    mode_purpose: str
    allowed_tool_names: tuple[str, ...]
    blocked_tool_names: tuple[str, ...]
    cwd: Path
    allowed_dirs: tuple[Path, ...]
    platform: str


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
            "允许访问目录：",
            *[f"- {path}" for path in context.allowed_dirs],
            f"当前平台：{context.platform}",
            "</system-reminder>",
        ]
        return {"role": "user", "content": "\n".join(lines)}


def collect_runtime_reminder_context(
    mode: AgentMode,
    all_tool_names: tuple[str, ...],
    allowed_tool_names: tuple[str, ...],
    tool_context: ToolExecutionContext,
) -> ReminderContext:
    allowed = tuple(name for name in all_tool_names if name in set(allowed_tool_names))
    blocked = tuple(name for name in all_tool_names if name not in set(allowed_tool_names))
    return ReminderContext(
        mode_name=mode.name,
        mode_purpose=mode.purpose,
        allowed_tool_names=allowed,
        blocked_tool_names=blocked,
        cwd=tool_context.default_cwd or Path.cwd(),
        allowed_dirs=tuple(tool_context.path_policy.allowed_roots),
        platform=_current_platform(),
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
