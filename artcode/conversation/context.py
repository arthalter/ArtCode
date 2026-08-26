from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass, replace
from collections.abc import Sequence
from typing import Any, Iterable, Protocol

from artcode.prompts import SYSTEM_PROMPT
from artcode.providers.tool_calls import ToolCall
from artcode.tools.results import ToolResult, error_result


Message = dict[str, Any]


class ConversationPersistenceRejected(RuntimeError):
    pass


@dataclass
class ConversationEntry:
    id: str
    payload: Message
    mode: str = "normal"
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


class ConversationEntryObserver(Protocol):
    def validate_entry(self, entry: ConversationEntry) -> None:
        ...

    def on_entry(self, entry: ConversationEntry) -> None:
        ...


class ConversationContext:
    def __init__(
        self,
        system_prompt: str = SYSTEM_PROMPT,
        observer: ConversationEntryObserver | None = None,
    ) -> None:
        self._next_id = 1
        self._version = 0
        self._observer = observer
        self._last_observer_error: Exception | None = None
        self._entries: list[ConversationEntry] = [
            self._make_entry({"role": "system", "content": system_prompt})
        ]
        self._user_archive: dict[str, UserMessageRecord] = {}

    @classmethod
    def from_persisted_records(
        cls,
        records: Iterable[Any],
        *,
        system_prompt: str = SYSTEM_PROMPT,
        observer: ConversationEntryObserver | None = None,
    ) -> "ConversationContext":
        context = cls(system_prompt=system_prompt, observer=None)
        system_entry = context._entries[0]
        restored: list[ConversationEntry] = [system_entry]
        user_archive: dict[str, UserMessageRecord] = {}
        max_id = 0
        for record in records:
            entry_id = str(record.entry_id)
            payload = deepcopy(record.message)
            mode = str(record.mode)
            raw_result = _tool_result_from_message(payload) if payload.get("role") == "tool" else None
            entry = ConversationEntry(entry_id, payload, mode, raw_result)
            restored.append(entry)
            if payload.get("role") == "user" and isinstance(payload.get("content"), str):
                user_archive[entry_id] = UserMessageRecord(
                    entry_id, payload["content"], len(user_archive)
                )
            if entry_id.startswith("msg-") and entry_id[4:].isdigit():
                max_id = max(max_id, int(entry_id[4:]))
        context._entries = restored
        context._user_archive = user_archive
        context._next_id = max(max_id + 1, context._next_id)
        context._version = 0
        context._observer = observer
        context._last_observer_error = None
        return context

    @classmethod
    def from_messages(
        cls,
        messages: Sequence[Message],
        *,
        observer: ConversationEntryObserver | None = None,
    ) -> "ConversationContext":
        """Build an isolated context from an already prepared model request."""
        if not messages:
            raise ValueError("messages cannot be empty")
        context = cls(observer=None)
        context._entries = []
        context._next_id = 1
        context._version = 0
        context._user_archive = {}
        for payload in messages:
            copied = deepcopy(payload)
            raw = _tool_result_from_message(copied) if copied.get("role") == "tool" else None
            entry = context._make_entry(copied, raw_tool_result=raw)
            context._entries.append(entry)
            if copied.get("role") == "user" and isinstance(copied.get("content"), str):
                context._user_archive[entry.id] = UserMessageRecord(
                    entry.id, copied["content"], len(context._user_archive)
                )
        context._observer = observer
        context._last_observer_error = None
        return context

    @property
    def version(self) -> int:
        return self._version

    @property
    def last_observer_error(self) -> Exception | None:
        return self._last_observer_error

    def bind_observer(self, observer: ConversationEntryObserver | None) -> None:
        self._observer = observer
        self._last_observer_error = None

    def append_user(self, content: str, *, mode: str = "normal") -> ConversationEntry:
        entry = self._append("user", content, mode=mode)
        self._user_archive[entry.id] = UserMessageRecord(entry.id, content, len(self._user_archive))
        return entry

    def append_assistant(self, content: str, *, mode: str = "normal") -> ConversationEntry:
        return self._append("assistant", content, mode=mode)

    def append_system(self, content: str, *, mode: str = "normal") -> ConversationEntry:
        return self._append("system", content, mode=mode)

    def append_assistant_tool_call(
        self,
        tool_calls: Sequence[ToolCall],
        *,
        reasoning_content: str = "",
        mode: str = "normal",
    ) -> ConversationEntry:
        payload: Message = {
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
        if reasoning_content:
            payload["reasoning_content"] = reasoning_content
        entry = self._make_entry(
            payload,
            mode=mode,
        )
        self._preflight(entry)
        self._entries.append(entry)
        self._changed()
        self._notify(entry)
        return entry

    def append_tool_result(
        self, tool_call: ToolCall, result: ToolResult, *, mode: str = "normal"
    ) -> ConversationEntry:
        entry = self._make_entry(
            _tool_result_message(tool_call, result), raw_tool_result=result, mode=mode
        )
        self._preflight(entry)
        self._entries.append(entry)
        self._changed()
        self._notify(entry)
        return entry

    def export_messages(self) -> list[Message]:
        return deepcopy([entry.payload for entry in self._entries])

    def snapshot(self) -> ConversationSnapshot:
        return ConversationSnapshot(self._version, tuple(deepcopy(self._entries)))

    @classmethod
    def from_snapshot(
        cls,
        snapshot: ConversationSnapshot,
        *,
        observer: ConversationEntryObserver | None = None,
    ) -> "ConversationContext":
        """Create an independent context from an instantaneous parent snapshot."""
        if not snapshot.entries:
            raise ValueError("conversation snapshot cannot be empty")
        context = cls(observer=observer)
        context._entries = list(deepcopy(snapshot.entries))
        context._version = snapshot.version
        context._next_id = 1
        context._user_archive = {}
        for ordinal, entry in enumerate(context._entries):
            payload = entry.payload
            if payload.get("role") == "user" and isinstance(payload.get("content"), str):
                context._user_archive[entry.id] = UserMessageRecord(entry.id, payload["content"], ordinal)
            if entry.id.startswith("msg-") and entry.id[4:].isdigit():
                context._next_id = max(context._next_id, int(entry.id[4:]) + 1)
        context._last_observer_error = None
        return context

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
        mode: str = "normal",
    ) -> ConversationEntry:
        return self._make_entry(
            payload,
            raw_tool_result=raw_tool_result,
            summarized_user_ids=summarized_user_ids,
            persistence_failed=persistence_failed,
            mode=mode,
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
                    self._make_entry(
                        _tool_result_message(tool_call, result),
                        raw_tool_result=result,
                        mode=self._entries[index].mode,
                    )
                )
                repaired.append((tool_call, result))

            if missing_entries:
                self._entries[following:following] = missing_entries
                self._changed()
                for entry in missing_entries:
                    self._notify(entry)
                following += len(missing_entries)
            index = following
        return repaired

    def _append(self, role: str, content: str, *, mode: str = "normal") -> ConversationEntry:
        entry = self._make_entry({"role": role, "content": content}, mode=mode)
        self._preflight(entry)
        self._entries.append(entry)
        self._changed()
        self._notify(entry)
        return entry

    def _make_entry(
        self,
        payload: Message,
        *,
        raw_tool_result: ToolResult | None = None,
        summarized_user_ids: tuple[str, ...] = (),
        persistence_failed: bool = False,
        mode: str = "normal",
    ) -> ConversationEntry:
        entry = ConversationEntry(
            id=f"msg-{self._next_id:08d}",
            payload=deepcopy(payload),
            mode=mode,
            raw_tool_result=raw_tool_result,
            summarized_user_ids=summarized_user_ids,
            persistence_failed=persistence_failed,
        )
        self._next_id += 1
        return entry

    def _notify(self, entry: ConversationEntry) -> None:
        if self._observer is not None:
            try:
                self._observer.on_entry(deepcopy(entry))
            except Exception as exc:
                entry.persistence_failed = True
                self._last_observer_error = exc

    def _preflight(self, entry: ConversationEntry) -> None:
        validator = getattr(self._observer, "validate_entry", None)
        if callable(validator):
            try:
                validator(deepcopy(entry))
            except Exception as exc:
                raise ConversationPersistenceRejected(str(exc)) from exc

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


def _tool_result_from_message(message: Message) -> ToolResult | None:
    try:
        payload = json.loads(message.get("content", ""))
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    required = {"tool_name", "ok", "status", "message", "content", "error_code", "bytes_returned"}
    if not required.issubset(payload):
        return None
    try:
        return ToolResult(
            tool_name=str(payload["tool_name"]),
            ok=bool(payload["ok"]),
            status=str(payload["status"]),
            message=str(payload["message"]),
            content=str(payload["content"]),
            error_code=None if payload["error_code"] is None else str(payload["error_code"]),
            bytes_returned=int(payload["bytes_returned"]),
        )
    except (TypeError, ValueError):
        return None
