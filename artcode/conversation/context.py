from __future__ import annotations

from copy import deepcopy
from typing import Any

from artcode.providers.tool_calls import ToolCall
from artcode.tools.results import ToolResult, error_result

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

    def repair_incomplete_tool_calls(
        self,
        error_code: str = "tool_execution_interrupted",
        message: str = "工具调用在产生结果前被中断。",
    ) -> list[tuple[ToolCall, ToolResult]]:
        """Insert structured results for every orphaned assistant tool call.

        OpenAI-compatible APIs require tool results to immediately follow the
        assistant tool_calls message. Repair therefore inserts missing results
        before any later user or assistant message instead of appending them at
        the end of the conversation.
        """

        repaired: list[tuple[ToolCall, ToolResult]] = []
        index = 0
        while index < len(self._messages):
            assistant = self._messages[index]
            raw_calls = assistant.get("tool_calls")
            if assistant.get("role") != "assistant" or not isinstance(raw_calls, list):
                index += 1
                continue

            following = index + 1
            completed_ids: set[str] = set()
            while following < len(self._messages) and self._messages[following].get("role") == "tool":
                tool_call_id = self._messages[following].get("tool_call_id")
                if isinstance(tool_call_id, str):
                    completed_ids.add(tool_call_id)
                following += 1

            missing_messages: list[Message] = []
            for raw_call in raw_calls:
                tool_call = _tool_call_from_message(raw_call)
                if tool_call is None or tool_call.id in completed_ids:
                    continue
                result = error_result(tool_call.name, error_code, message)
                missing_messages.append(_tool_result_message(tool_call, result))
                repaired.append((tool_call, result))

            if missing_messages:
                self._messages[following:following] = missing_messages
                following += len(missing_messages)
            index = following
        return repaired

    def _append(self, role: str, content: str) -> None:
        self._messages.append({"role": role, "content": content})


def _tool_call_from_message(raw_call: Any) -> ToolCall | None:
    if not isinstance(raw_call, dict):
        return None
    tool_call_id = raw_call.get("id")
    function = raw_call.get("function")
    if not isinstance(tool_call_id, str) or not isinstance(function, dict):
        return None
    name = function.get("name")
    arguments = function.get("arguments")
    if not isinstance(name, str) or not isinstance(arguments, str):
        return None
    return ToolCall(tool_call_id, name, arguments)


def _tool_result_message(tool_call: ToolCall, result: ToolResult) -> Message:
    return {
        "role": "tool",
        "tool_call_id": tool_call.id,
        "name": tool_call.name,
        "content": result.to_model_content(),
    }
