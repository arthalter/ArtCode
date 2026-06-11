from __future__ import annotations

from copy import deepcopy
from typing import Any

from artcode.providers.tool_calls import ToolCall
from artcode.tools.results import ToolResult

from artcode.prompts import SYSTEM_PROMPT


Message = dict[str, Any]


class ConversationContext:
    def __init__(self, system_prompt: str = SYSTEM_PROMPT) -> None:
        self._messages: list[Message] = [{"role": "system", "content": system_prompt}]

    def append_user(self, content: str) -> None:
        self._append("user", content)

    def append_assistant(self, content: str) -> None:
        self._append("assistant", content)

    def append_assistant_tool_call(self, tool_calls: list[ToolCall]) -> None:
        self._messages.append(
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": tool_call.id,
                        "type": "function",
                        "function": {
                            "name": tool_call.name,
                            "arguments": tool_call.arguments_json,
                        },
                    }
                    for tool_call in tool_calls
                ],
            }
        )

    def append_tool_result(self, tool_call: ToolCall, result: ToolResult) -> None:
        self._messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_call.id,
                "name": tool_call.name,
                "content": result.to_model_content(),
            }
        )

    def export_messages(self) -> list[Message]:
        return deepcopy(self._messages)

    def _append(self, role: str, content: str) -> None:
        self._messages.append({"role": role, "content": content})
