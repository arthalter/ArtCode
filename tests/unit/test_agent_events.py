from __future__ import annotations

from artcode.agent import AgentEventType, StopReason, TokenUsage
from artcode.agent.events import context_status_event, iteration_started_event, token_usage_event


def test_iteration_event_has_structured_payload() -> None:
    event = iteration_started_event(2, 12)

    assert event.type == AgentEventType.ITERATION_STARTED
    assert event.payload == {"current": 2, "maximum": 12}


def test_token_usage_round_trips_payload() -> None:
    usage = TokenUsage(prompt_tokens=1, completion_tokens=2, total_tokens=3, cached_tokens=4, cache_miss_tokens=5)

    assert token_usage_event(usage).payload == {
        "prompt_tokens": 1,
        "completion_tokens": 2,
        "total_tokens": 3,
        "cached_tokens": 4,
        "cache_miss_tokens": 5,
    }


def test_stop_reasons_are_named() -> None:
    assert StopReason.ITERATION_LIMIT.value == "iteration_limit"
    assert StopReason.UNKNOWN_TOOL.value == "unknown_tool"


def test_context_status_event_has_observable_fields() -> None:
    event = context_status_event("automatic", "success", 100, 20, 2, False)

    assert event.type == AgentEventType.CONTEXT_STATUS
    assert event.payload["before_tokens"] == 100
    assert event.payload["persisted_count"] == 2
