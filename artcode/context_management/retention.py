from __future__ import annotations

import json
from dataclasses import dataclass

from artcode.conversation import ConversationEntry, ConversationSnapshot

from .estimator import estimate_text_tokens
from .models import RECENT_HISTORY_TOKENS, RECENT_MINIMUM_MESSAGES


@dataclass(frozen=True)
class RetentionPlan:
    compactable_entries: tuple[ConversationEntry, ...]
    preserved_user_entries: tuple[ConversationEntry, ...]
    preserved_system_entries: tuple[ConversationEntry, ...]
    recent_entries: tuple[ConversationEntry, ...]
    summarized_user_ids: tuple[str, ...]

    @property
    def can_compact(self) -> bool:
        return bool(self.compactable_entries)


class RetentionPlanner:
    def __init__(
        self,
        recent_token_budget: int = RECENT_HISTORY_TOKENS,
        minimum_messages: int = RECENT_MINIMUM_MESSAGES,
    ) -> None:
        self.recent_token_budget = recent_token_budget
        self.minimum_messages = minimum_messages

    def plan(self, snapshot: ConversationSnapshot) -> RetentionPlan:
        entries = snapshot.entries
        if len(entries) <= 1:
            return RetentionPlan((), (), (), entries[1:], ())

        units = _history_units(entries)
        tokens = 0
        message_count = 0
        recent_start = len(entries)
        for start, end in reversed(units):
            unit = entries[start:end]
            tokens += sum(_entry_tokens(entry) for entry in unit)
            message_count += sum(1 for entry in unit if _counts_as_recent_message(entry))
            recent_start = start
            if tokens >= self.recent_token_budget and message_count >= self.minimum_messages:
                break

        protected_indexes = [
            index
            for index, entry in enumerate(entries[1:], start=1)
            if entry.persistence_failed
        ]
        if protected_indexes:
            protected_start = _unit_start_for_index(units, min(protected_indexes))
            recent_start = min(recent_start, protected_start)

        if recent_start <= 1:
            return RetentionPlan((), (), (), entries[1:], ())

        historical = entries[1:recent_start]
        preserved_users = tuple(
            entry for entry in historical if entry.payload.get("role") == "user"
        )
        preserved_system = tuple(
            entry
            for entry in historical
            if entry.payload.get("role") == "system" and entry.mode == "subagent"
        )
        compactable = tuple(
            entry
            for entry in historical
            if entry.payload.get("role") != "user" and entry not in preserved_system
        )
        recent = entries[recent_start:]
        summarized_ids: list[str] = []
        seen: set[str] = set()
        actual_user_ids = {
            entry.id for entry in entries if entry.payload.get("role") == "user"
        }
        for entry in historical:
            for user_id in entry.summarized_user_ids:
                if user_id not in actual_user_ids and user_id not in seen:
                    summarized_ids.append(user_id)
                    seen.add(user_id)
            if entry.payload.get("role") == "user" and entry.id not in seen:
                summarized_ids.append(entry.id)
                seen.add(entry.id)

        if not compactable:
            return RetentionPlan((), (), (), entries[1:], ())
        return RetentionPlan(
            compactable,
            preserved_users,
            preserved_system,
            recent,
            tuple(summarized_ids),
        )


def is_conversation_summary(entry: ConversationEntry) -> bool:
    content = entry.payload.get("content")
    return (
        entry.payload.get("role") == "system"
        and isinstance(content, str)
        and content.startswith("<conversation-summary>")
    )


def _history_units(entries: tuple[ConversationEntry, ...]) -> list[tuple[int, int]]:
    units: list[tuple[int, int]] = []
    index = 1
    while index < len(entries):
        entry = entries[index]
        if entry.payload.get("role") == "assistant" and isinstance(entry.payload.get("tool_calls"), list):
            end = index + 1
            while end < len(entries) and entries[end].payload.get("role") == "tool":
                end += 1
            units.append((index, end))
            index = end
        else:
            units.append((index, index + 1))
            index += 1
    return units


def _unit_start_for_index(units: list[tuple[int, int]], index: int) -> int:
    for start, end in units:
        if start <= index < end:
            return start
    return index


def _entry_tokens(entry: ConversationEntry) -> int:
    serialized = json.dumps(
        entry.payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return estimate_text_tokens(serialized)


def _counts_as_recent_message(entry: ConversationEntry) -> bool:
    return entry.payload.get("role") != "system" and not is_conversation_summary(entry)
