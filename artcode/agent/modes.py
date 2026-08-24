from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from artcode.tools import ToolDescriptor, ToolEffect, ToolOrigin


@dataclass(frozen=True)
class ToolAccessPolicy:
    allowed_effects: frozenset[ToolEffect] | None = None
    allowed_names: frozenset[str] | None = None

    def restricted_to(self, names: frozenset[str] | set[str]) -> "ToolAccessPolicy":
        return ToolAccessPolicy(self.allowed_effects, frozenset(names))

    def allows(self, descriptor: ToolDescriptor) -> bool:
        if descriptor.origin is ToolOrigin.SYSTEM:
            return True
        if self.allowed_names is not None and descriptor.name not in self.allowed_names:
            return False
        if descriptor.origin is ToolOrigin.MCP:
            return True
        if self.allowed_effects is None:
            return True
        return descriptor.effect in self.allowed_effects

    def filter_openai_tools(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if self.allowed_effects is None and self.allowed_names is None:
            return list(tools)
        filtered: list[dict[str, Any]] = []
        for tool in tools:
            function = tool.get("function")
            if not isinstance(function, dict):
                continue
            name = function.get("name")
            origin = tool.get("x-artcode-origin", "builtin")
            effect = tool.get("x-artcode-effect")
            if not isinstance(name, str):
                continue
            if origin == ToolOrigin.SYSTEM.value:
                filtered.append(tool)
                continue
            if self.allowed_names is not None and name not in self.allowed_names:
                continue
            if origin == ToolOrigin.MCP.value:
                filtered.append(tool)
                continue
            try:
                selected_effect = ToolEffect(effect)
            except (TypeError, ValueError):
                continue
            if self.allowed_effects is None or selected_effect in self.allowed_effects:
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
    tool_policy=ToolAccessPolicy(frozenset({ToolEffect.READ})),
    purpose="只读规划模式，只允许读取文件、查找文件和搜索文本。",
)

DO_MODE = AgentMode(
    name="do",
    tool_policy=ToolAccessPolicy(),
    purpose="执行最近计划，使用全工具自主循环完成任务。",
)
