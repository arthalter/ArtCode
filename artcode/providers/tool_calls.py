from __future__ import annotations

import json
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
            if not isinstance(item, dict):
                raise ValueError("tool call delta must be an object")
            index = item.get("index")
            if isinstance(index, bool) or not isinstance(index, int) or index < 0:
                raise ValueError("tool call delta requires a non-negative integer index")
            partial = self._partials.setdefault(index, _PartialToolCall())

            tool_call_id = item.get("id")
            if tool_call_id is not None:
                if not isinstance(tool_call_id, str):
                    raise ValueError("tool call id delta must be a string")
                partial.id += tool_call_id

            function = item.get("function")
            if function is not None:
                if not isinstance(function, dict):
                    raise ValueError("tool call function delta must be an object")
                name = function.get("name")
                if name is not None:
                    if not isinstance(name, str):
                        raise ValueError("tool call name delta must be a string")
                    partial.name += name
                arguments = function.get("arguments")
                if arguments is not None:
                    if not isinstance(arguments, str):
                        raise ValueError("tool call arguments delta must be a string")
                    partial.arguments += arguments

    def has_calls(self) -> bool:
        return bool(self._partials)

    def finish(self) -> tuple[ToolCall, ...]:
        calls: list[ToolCall] = []
        for index in sorted(self._partials):
            partial = self._partials[index]
            if not partial.name:
                raise ValueError(f"tool call {index} has no function name")
            arguments = partial.arguments or "{}"
            try:
                json.loads(arguments)
            except json.JSONDecodeError as exc:
                raise ValueError(f"tool call {index} has invalid JSON arguments") from exc
            calls.append(
                ToolCall(
                    id=partial.id or f"call_{index}",
                    name=partial.name,
                    arguments_json=arguments,
                )
            )
        return tuple(calls)
