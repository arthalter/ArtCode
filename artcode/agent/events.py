from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

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
    TOOL_CALLS_RECEIVED = "tool_calls_received"
    TOOL_BATCH_STARTED = "tool_batch_started"
    TOOL_RESULT = "tool_result"
    TOKEN_USAGE = "token_usage"
    FINAL_SUMMARY_STARTED = "final_summary_started"
    STOPPED = "stopped"


@dataclass(frozen=True)
class TokenUsage:
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    cached_tokens: int | None = None
    cache_miss_tokens: int | None = None

    @classmethod
    def from_event_payload(cls, payload: dict[str, Any]) -> "TokenUsage":
        return cls(
            prompt_tokens=_optional_int(payload.get("prompt_tokens")),
            completion_tokens=_optional_int(payload.get("completion_tokens")),
            total_tokens=_optional_int(payload.get("total_tokens")),
            cached_tokens=_optional_int(payload.get("cached_tokens")),
            cache_miss_tokens=_optional_int(payload.get("cache_miss_tokens")),
        )

    def to_payload(self) -> dict[str, int | None]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "cached_tokens": self.cached_tokens,
            "cache_miss_tokens": self.cache_miss_tokens,
        }


@dataclass(frozen=True)
class ModelTurn:
    text: str
    tool_calls: list[ToolCall]
    usage: TokenUsage | None = None


@dataclass(frozen=True)
class AgentEvent:
    type: AgentEventType
    payload: dict[str, Any]


def run_started_event(mode: str, max_iterations: int) -> AgentEvent:
    return AgentEvent(
        AgentEventType.RUN_STARTED,
        {"mode": mode, "max_iterations": max_iterations},
    )


def iteration_started_event(current: int, maximum: int) -> AgentEvent:
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


def stopped_event(reason: StopReason, message: str = "") -> AgentEvent:
    return AgentEvent(AgentEventType.STOPPED, {"reason": reason.value, "message": message})


def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None
