from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from collections.abc import Mapping
import hashlib
import json
import re
from typing import Any, Protocol

from artcode.providers.events import TokenUsage
from artcode.providers.tool_calls import ToolCall
from artcode.tools import ToolResult


class StopReason(StrEnum):
    NATURAL = "natural"
    ITERATION_LIMIT = "iteration_limit"
    UNKNOWN_TOOL = "unknown_tool"
    USER_CANCELLED = "user_cancelled"
    STREAM_ERROR = "stream_error"


class AgentEventType(StrEnum):
    RUN_STARTED = "run_started"
    ITERATION_STARTED = "iteration_started"
    TEXT_DELTA = "text_delta"
    MODEL_TURN_COMPLETED = "model_turn_completed"
    MODEL_REQUEST = "model_request"
    TOOL_CALLS_RECEIVED = "tool_calls_received"
    TOOL_BATCH_STARTED = "tool_batch_started"
    TOOL_RESULT = "tool_result"
    TOKEN_USAGE = "token_usage"
    FINAL_SUMMARY_STARTED = "final_summary_started"
    CONTEXT_STATUS = "context_status"
    PERMISSION_AUDIT = "permission_audit"
    STOPPED = "stopped"


@dataclass(frozen=True)
class ModelTurn:
    text: str
    reasoning_content: str
    tool_calls: tuple[ToolCall, ...]
    usage: TokenUsage | None = None
    finish_reason: str | None = None


@dataclass(frozen=True)
class CompletedTurn:
    session_id: str
    mode: str
    user_content: str
    final_text: str
    entry_ids: tuple[str, ...]
    tool_summaries: tuple[Mapping[str, Any], ...] = ()


class CompletedTurnObserver(Protocol):
    def submit(self, turn: CompletedTurn) -> None:
        ...


@dataclass(frozen=True)
class AgentEvent:
    type: AgentEventType
    payload: dict[str, Any]


def run_started_event(mode: str, max_iterations: int | None) -> AgentEvent:
    return AgentEvent(
        AgentEventType.RUN_STARTED,
        {"mode": mode, "max_iterations": max_iterations},
    )


def iteration_started_event(current: int, maximum: int | None) -> AgentEvent:
    return AgentEvent(
        AgentEventType.ITERATION_STARTED,
        {"current": current, "maximum": maximum},
    )


def text_delta_event(text: str) -> AgentEvent:
    return AgentEvent(AgentEventType.TEXT_DELTA, {"text": text})


def model_turn_completed_event(text: str, tool_call_count: int) -> AgentEvent:
    return AgentEvent(
        AgentEventType.MODEL_TURN_COMPLETED,
        {"text": text, "tool_call_count": tool_call_count},
    )


def model_request_event(tools: tuple[dict[str, Any], ...] | None) -> AgentEvent:
    """Describe the exact tool-definition payload without storing its contents."""

    definitions = [] if tools is None else list(tools)
    canonical = json.dumps(
        definitions,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    encoded = canonical.encode("utf-8")
    return AgentEvent(
        AgentEventType.MODEL_REQUEST,
        {
            "tool_count": len(definitions),
            "tool_definition_bytes": len(encoded),
            "tool_definition_tokens": len(
                re.findall(r"[\w]+|[^\w\s]", canonical, flags=re.UNICODE)
            ),
            "tokenizer": "utf8_regex_v1",
            "tool_payload_sha256": hashlib.sha256(encoded).hexdigest(),
        },
    )


def permission_audit_event(event: str, **payload: Any) -> AgentEvent:
    return AgentEvent(
        AgentEventType.PERMISSION_AUDIT,
        {"event": event, **payload},
    )


def tool_calls_received_event(count: int) -> AgentEvent:
    return AgentEvent(AgentEventType.TOOL_CALLS_RECEIVED, {"count": count})


def tool_batch_started_event(index: int, safety: str, count: int) -> AgentEvent:
    return AgentEvent(
        AgentEventType.TOOL_BATCH_STARTED,
        {"index": index, "safety": safety, "count": count},
    )


def tool_result_event(tool_call: ToolCall, result: ToolResult) -> AgentEvent:
    return AgentEvent(
        AgentEventType.TOOL_RESULT,
        {"tool_call": tool_call, "result": result},
    )


def token_usage_event(usage: TokenUsage) -> AgentEvent:
    return AgentEvent(AgentEventType.TOKEN_USAGE, usage.to_payload())


def final_summary_started_event(reason: StopReason) -> AgentEvent:
    return AgentEvent(AgentEventType.FINAL_SUMMARY_STARTED, {"reason": reason.value})


def context_status_event(
    trigger: str,
    status: str,
    before_tokens: int,
    after_tokens: int,
    persisted_count: int,
    circuit_open: bool,
    message: str = "",
) -> AgentEvent:
    return AgentEvent(
        AgentEventType.CONTEXT_STATUS,
        {
            "trigger": trigger,
            "status": status,
            "before_tokens": before_tokens,
            "after_tokens": after_tokens,
            "persisted_count": persisted_count,
            "circuit_open": circuit_open,
            "message": message,
        },
    )


def stopped_event(reason: StopReason, message: str = "") -> AgentEvent:
    return AgentEvent(AgentEventType.STOPPED, {"reason": reason.value, "message": message})
