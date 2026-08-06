from __future__ import annotations

from dataclasses import dataclass
from typing import Any


READ_ONLY_TOOL_NAMES = frozenset({"read_file", "find_files", "search_text"})


@dataclass(frozen=True)
class ToolAccessPolicy:
    allowed_tool_names: frozenset[str] | None = None

    def allows(self, tool_name: str) -> bool:
        if self.allowed_tool_names is None:
            return True
        return tool_name in self.allowed_tool_names

    def filter_openai_tools(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if self.allowed_tool_names is None:
            return list(tools)
        filtered: list[dict[str, Any]] = []
        for tool in tools:
            function = tool.get("function")
            if not isinstance(function, dict):
                continue
            name = function.get("name")
            origin = tool.get("x-artcode-origin", "builtin")
            if isinstance(name, str) and (origin == "mcp" or self.allows(name)):
                filtered.append(tool)
        return filtered


@dataclass(frozen=True)
class AgentMode:
    name: str
    tool_policy: ToolAccessPolicy
    purpose: str


NORMAL_AGENT_MODE = AgentMode(
    name="normal",
    tool_policy=ToolAccessPolicy(),
    purpose="普通用户输入，使用全工具自主循环完成任务。",
)

PLAN_MODE = AgentMode(
    name="plan",
    tool_policy=ToolAccessPolicy(READ_ONLY_TOOL_NAMES),
    purpose="只读规划模式，只允许读取文件、查找文件和搜索文本。",
)

DO_MODE = AgentMode(
    name="do",
    tool_policy=ToolAccessPolicy(),
    purpose="执行最近计划，使用全工具自主循环完成任务。",
)
