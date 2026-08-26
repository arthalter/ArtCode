from __future__ import annotations

from copy import deepcopy
from typing import Any

from .base import Tool, ToolDescriptor


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        descriptor = _require_descriptor(tool)
        if descriptor.name in self._tools:
            raise ValueError(f"Tool already registered: {descriptor.name}")
        self._tools[descriptor.name] = tool

    def register_many(self, tools: list[Tool] | tuple[Tool, ...]) -> list[str]:
        issues: list[str] = []
        for tool in tools:
            descriptor = _require_descriptor(tool)
            if descriptor.name in self._tools:
                issues.append(f"Tool already registered: {descriptor.name}")
                continue
            self._tools[descriptor.name] = tool
        return issues

    def all(self) -> tuple[Tool, ...]:
        return tuple(self._tools.values())

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def require(self, name: str) -> Tool:
        tool = self.get(name)
        if tool is None:
            raise KeyError(f"Unknown tool: {name}")
        return tool

    def descriptor(self, name: str) -> ToolDescriptor | None:
        tool = self.get(name)
        return None if tool is None else tool.descriptor

    def descriptors(self) -> tuple[ToolDescriptor, ...]:
        return tuple(tool.descriptor for tool in self._tools.values())

    def openai_tools(self, *, include_internal_metadata: bool = False) -> list[dict[str, Any]]:
        result = [
            ({
                "type": "function",
                "x-artcode-origin": tool.descriptor.origin.value,
                "x-artcode-effect": tool.descriptor.effect.value,
                "x-artcode-rule-configurable": tool.descriptor.rule_configurable,
                "x-artcode-subagent-allowed": tool.descriptor.subagent_allowed,
                "function": {
                    "name": tool.descriptor.name,
                    "description": tool.descriptor.description,
                    "parameters": deepcopy(dict(tool.descriptor.parameters_schema)),
                },
            } if include_internal_metadata else {
                "type": "function",
                "function": {
                    "name": tool.descriptor.name,
                    "description": tool.descriptor.description,
                    "parameters": deepcopy(dict(tool.descriptor.parameters_schema)),
                },
            })
            for tool in self._tools.values()
        ]
        return result


def create_default_tool_registry() -> ToolRegistry:
    from .command_tool import RunCommandTool
    from .file_tools import EditFileTool, FindFilesTool, ReadFileTool, SearchTextTool, WriteFileTool

    registry = ToolRegistry()
    for tool in (
        ReadFileTool(),
        WriteFileTool(),
        EditFileTool(),
        RunCommandTool(),
        FindFilesTool(),
        SearchTextTool(),
    ):
        registry.register(tool)
    return registry


def _require_descriptor(tool: Tool) -> ToolDescriptor:
    descriptor = getattr(tool, "descriptor", None)
    if not isinstance(descriptor, ToolDescriptor):
        raise TypeError("registered tools must expose a ToolDescriptor")
    return descriptor
