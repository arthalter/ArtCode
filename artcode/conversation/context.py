from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from typing import Any, Iterable

from artcode.prompts import SYSTEM_PROMPT
from artcode.providers.tool_calls import ToolCall
from artcode.tools.results import ToolResult, error_result


Message = dict[str, Any]


@dataclass
class ConversationEntry:
    id: str
    payload: Message
    raw_tool_result: ToolResult | None = None
    summarized_user_ids: tuple[str, ...] = ()
    persistence_failed: bool = False


@dataclass(frozen=True)
class ConversationSnapshot:
    version: int
    entries: tuple[ConversationEntry, ...]


@dataclass(frozen=True)
class UserMessageRecord:
    id: str
    content: str
    ordinal: int


class ConversationContext:
    def __init__(self, system_prompt: str = SYSTEM_PROMPT) -> None:
        self._next_id = 1
        self._version = 0
        self._entries: list[ConversationEntry] = [
            self._make_entry({"role": "system", "content": system_prompt})
        ]
        self._user_archive: dict[str, UserMessageRecord] = {}

    @property
    def version(self) -> int:
        return self._version

    def append_user(self, content: str) -> None:
        entry = self._append("user", content)
        self._user_archive[entry.id] = UserMessageRecord(entry.id, content, len(self._user_archive))

    def append_assistant(self, content: str) -> None:
        self._append("assistant", content)

    def append_assistant_tool_call(self, tool_calls: list[ToolCall]) -> None:
        self._entries.append(
            self._make_entry(
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
        )
        self._changed()

    def append_tool_result(self, tool_call: ToolCall, result: ToolResult) -> None:
        self._entries.append(
            self._make_entry(_tool_result_message(tool_call, result), raw_tool_result=result)
        )
        self._changed()

    def export_messages(self) -> list[Message]:
        return deepcopy([entry.payload for entry in self._entries])

    def snapshot(self) -> ConversationSnapshot:
        return ConversationSnapshot(self._version, tuple(deepcopy(self._entries)))

    def user_records(self, ids: Iterable[str]) -> tuple[UserMessageRecord, ...]:
        records = [self._user_archive[item] for item in ids if item in self._user_archive]
        return tuple(sorted(records, key=lambda item: item.ordinal))

    def replace_entry_content(
        self,
        entry_id: str,
        content: str,
        *,
        persistence_failed: bool = False,
    ) -> bool:
        for index, entry in enumerate(self._entries):
            if entry.id != entry_id:
                continue
            payload = deepcopy(entry.payload)
            payload["content"] = content
            self._entries[index] = replace(
                entry,
                payload=payload,
                persistence_failed=persistence_failed,
            )
            self._changed()
            return True
        return False

    def mark_persistence_failed(self, entry_id: str) -> bool:
        for index, entry in enumerate(self._entries):
            if entry.id == entry_id:
                self._entries[index] = replace(entry, persistence_failed=True)
                self._changed()
                return True
        return False

    def replace_entries_if_version(
        self,
        expected_version: int,
        entries: Iterable[ConversationEntry],
    ) -> bool:
        if self._version != expected_version:
            return False
        self._entries = list(deepcopy(tuple(entries)))
        self._changed()
        return True

    def make_entry(
        self,
        payload: Message,
        *,
        raw_tool_result: ToolResult | None = None,
        summarized_user_ids: tuple[str, ...] = (),
        persistence_failed: bool = False,
    ) -> ConversationEntry:
        return self._make_entry(
            payload,
            raw_tool_result=raw_tool_result,
            summarized_user_ids=summarized_user_ids,
            persistence_failed=persistence_failed,
        )

    def repair_incomplete_tool_calls(
        self,
        error_code: str = "tool_execution_interrupted",
        message: str = "工具调用在产生结果前被中断。",
    ) -> list[tuple[ToolCall, ToolResult]]:
        repaired: list[tuple[ToolCall, ToolResult]] = []
        index = 0
        while index < len(self._entries):
            assistant = self._entries[index].payload
            raw_calls = assistant.get("tool_calls")
            if assistant.get("role") != "assistant" or not isinstance(raw_calls, list):
                index += 1
                continue

            following = index + 1
            completed_ids: set[str] = set()
            while following < len(self._entries) and self._entries[following].payload.get("role") == "tool":
                tool_call_id = self._entries[following].payload.get("tool_call_id")
                if isinstance(tool_call_id, str):
                    completed_ids.add(tool_call_id)
                following += 1

            missing_entries: list[ConversationEntry] = []
            for raw_call in raw_calls:
                tool_call = _tool_call_from_message(raw_call)
                if tool_call is None or tool_call.id in completed_ids:
                    continue
                result = error_result(tool_call.name, error_code, message)
                missing_entries.append(
                    self._make_entry(_tool_result_message(tool_call, result), raw_tool_result=result)
                )
                repaired.append((tool_call, result))

            if missing_entries:
                self._entries[following:following] = missing_entries
                self._changed()
                following += len(missing_entries)
            index = following
        return repaired

    def _append(self, role: str, content: str) -> ConversationEntry:
        entry = self._make_entry({"role": role, "content": content})
        self._entries.append(entry)
        self._changed()
        return entry

    def _make_entry(
        self,
        payload: Message,
        *,
        raw_tool_result: ToolResult | None = None,
        summarized_user_ids: tuple[str, ...] = (),
        persistence_failed: bool = False,
    ) -> ConversationEntry:
        entry = ConversationEntry(
            id=f"msg-{self._next_id:08d}",
            payload=deepcopy(payload),
            raw_tool_result=raw_tool_result,
            summarized_user_ids=summarized_user_ids,
            persistence_failed=persistence_failed,
        )
        self._next_id += 1
        return entry

    def _changed(self) -> None:
        self._version += 1


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
