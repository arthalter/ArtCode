from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments_json: str


@dataclass
class _PartialToolCall:
    id: str = ""
    name: str = ""
    arguments: str = ""


class ToolCallAccumulator:
    def __init__(self) -> None:
        self._partials: dict[int, _PartialToolCall] = {}

    def add_delta(self, delta_tool_calls: list[dict[str, Any]]) -> None:
        for item in delta_tool_calls:
            index = item.get("index")
            if not isinstance(index, int):
                continue
            partial = self._partials.setdefault(index, _PartialToolCall())

            tool_call_id = item.get("id")
            if isinstance(tool_call_id, str) and tool_call_id:
                partial.id = tool_call_id

            function = item.get("function")
            if isinstance(function, dict):
                name = function.get("name")
                if isinstance(name, str) and name:
                    partial.name = name
                arguments = function.get("arguments")
                if isinstance(arguments, str):
                    partial.arguments += arguments

    def has_calls(self) -> bool:
        return bool(self._partials)

    def finish(self) -> list[ToolCall]:
        calls: list[ToolCall] = []
        for index in sorted(self._partials):
            partial = self._partials[index]
            calls.append(
                ToolCall(
                    id=partial.id or f"call_{index}",
                    name=partial.name,
                    arguments_json=partial.arguments,
                )
            )
        return calls
