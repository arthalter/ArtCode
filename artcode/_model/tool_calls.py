from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from artcode.core.model import ToolRequest


@dataclass(slots=True)
class _Partial:
    id: str = ""
    name: str = ""
    arguments: str = ""


class ToolCallAccumulator:
    def __init__(self) -> None:
        self._partials: dict[int, _Partial] = {}

    @property
    def has_calls(self) -> bool:
        return bool(self._partials)

    def add(self, values: list[Any]) -> None:
        for value in values:
            if not isinstance(value, dict):
                raise ValueError("tool call delta must be an object")
            index = value.get("index")
            if isinstance(index, bool) or not isinstance(index, int) or index < 0:
                raise ValueError("tool call delta requires a non-negative index")
            partial = self._partials.setdefault(index, _Partial())
            identifier = value.get("id")
            if identifier is not None:
                if not isinstance(identifier, str):
                    raise ValueError("tool call id delta must be text")
                partial.id += identifier
            function = value.get("function")
            if function is not None:
                if not isinstance(function, dict):
                    raise ValueError("tool call function delta must be an object")
                name = function.get("name")
                arguments = function.get("arguments")
                if name is not None:
                    if not isinstance(name, str):
                        raise ValueError("tool call name delta must be text")
                    partial.name += name
                if arguments is not None:
                    if not isinstance(arguments, str):
                        raise ValueError("tool call arguments delta must be text")
                    partial.arguments += arguments

    def finish(self) -> tuple[ToolRequest, ...]:
        calls: list[ToolRequest] = []
        for index in sorted(self._partials):
            partial = self._partials[index]
            if not partial.name:
                raise ValueError(f"tool call {index} has no function name")
            calls.append(
                ToolRequest(
                    partial.id or f"call_{index}",
                    partial.name,
                    partial.arguments or "{}",
                )
            )
        return tuple(calls)
