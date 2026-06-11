from __future__ import annotations

from typing import Any

from .base import Tool


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def require(self, name: str) -> Tool:
        tool = self.get(name)
        if tool is None:
            raise KeyError(f"Unknown tool: {name}")
        return tool

    def openai_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters_schema,
                },
            }
            for tool in self._tools.values()
        ]


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
