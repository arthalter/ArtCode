from __future__ import annotations

from dataclasses import dataclass

from artcode.conversation import ConversationContext, ConversationEntry

from .artifacts import ContextArtifactStore, is_persisted_output
from .estimator import estimate_text_tokens
from .models import (
    AGGREGATE_TOOL_RESULT_TOKENS,
    SINGLE_TOOL_RESULT_TOKENS,
    LightweightReport,
    PersistenceFailure,
)


@dataclass(frozen=True)
class _Candidate:
    entry: ConversationEntry
    message_index: int
    tokens: int


class LightweightCompactor:
    def __init__(self, artifact_store: ContextArtifactStore) -> None:
        self.artifact_store = artifact_store

    def apply(self, conversation: ConversationContext) -> LightweightReport:
        snapshot = conversation.snapshot()
        before_tokens = _tool_message_tokens(snapshot.entries)
        persisted_ids: set[str] = set()
        failed_ids: set[str] = set()
        failures: list[PersistenceFailure] = []

        for group in _tool_result_groups(snapshot.entries):
            candidates = _candidates(group)
            for candidate in candidates:
                if candidate.tokens <= SINGLE_TOOL_RESULT_TOKENS:
                    continue
                if self._persist(conversation, candidate, failures):
                    persisted_ids.add(candidate.entry.id)
                else:
                    failed_ids.add(candidate.entry.id)

            remaining = [
                candidate
                for candidate in candidates
                if candidate.entry.id not in persisted_ids
                and candidate.entry.id not in failed_ids
            ]
            remaining_tokens = sum(candidate.tokens for candidate in remaining)
            if remaining_tokens > AGGREGATE_TOOL_RESULT_TOKENS:
                for candidate in sorted(
                    remaining,
                    key=lambda item: (-item.tokens, item.message_index),
                ):
                    if remaining_tokens <= AGGREGATE_TOOL_RESULT_TOKENS:
                        break
                    if self._persist(conversation, candidate, failures):
                        persisted_ids.add(candidate.entry.id)
                        remaining_tokens -= candidate.tokens
                    else:
                        failed_ids.add(candidate.entry.id)

        after_tokens = _tool_message_tokens(conversation.snapshot().entries)
        return LightweightReport(
            persisted_count=len(persisted_ids),
            before_tokens=before_tokens,
            after_tokens=after_tokens,
            failures=tuple(failures),
        )

    def _persist(
        self,
        conversation: ConversationContext,
        candidate: _Candidate,
        failures: list[PersistenceFailure],
    ) -> bool:
        if candidate.entry.persistence_failed:
            return False
        try:
            persisted = self.artifact_store.persist(candidate.entry)
        except Exception as exc:
            conversation.mark_persistence_failed(candidate.entry.id)
            failures.append(PersistenceFailure(candidate.entry.id, str(exc)))
            return False
        try:
            committed = conversation.replace_entry_content(
                candidate.entry.id,
                persisted.marker,
            )
        except Exception as exc:
            committed = False
            failures.append(PersistenceFailure(candidate.entry.id, str(exc)))
        if not committed:
            try:
                self.artifact_store.discard(persisted)
            except OSError:
                pass
            if not any(item.entry_id == candidate.entry.id for item in failures):
                failures.append(
                    PersistenceFailure(
                        candidate.entry.id,
                        "工具结果存盘期间对话发生变化，未提交 marker。",
                    )
                )
        return committed


def _tool_result_groups(entries: tuple[ConversationEntry, ...]):
    index = 0
    while index < len(entries):
        entry = entries[index]
        if entry.payload.get("role") != "assistant" or not isinstance(entry.payload.get("tool_calls"), list):
            index += 1
            continue
        following = index + 1
        group: list[tuple[int, ConversationEntry]] = []
        while following < len(entries) and entries[following].payload.get("role") == "tool":
            group.append((following, entries[following]))
            following += 1
        if group:
            yield group
        index = following


def _candidates(group: list[tuple[int, ConversationEntry]]) -> list[_Candidate]:
    candidates: list[_Candidate] = []
    for message_index, entry in group:
        content = entry.payload.get("content")
        if entry.persistence_failed or is_persisted_output(content) or entry.raw_tool_result is None:
            continue
        candidates.append(
            _Candidate(
                entry=entry,
                message_index=message_index,
                tokens=estimate_text_tokens(entry.raw_tool_result.content),
            )
        )
    return candidates


def _tool_message_tokens(entries: tuple[ConversationEntry, ...]) -> int:
    total = 0
    for entry in entries:
        if entry.payload.get("role") == "tool":
            total += estimate_text_tokens(str(entry.payload.get("content", "")))
    return total
