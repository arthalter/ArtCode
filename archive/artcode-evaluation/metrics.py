from __future__ import annotations

from collections import Counter
from typing import Iterable

from .models import (
    AttemptMetrics,
    JudgeResult,
    JudgeStatus,
    MetricValue,
    TraceRecord,
    VerificationResult,
)


_PERMISSION_ERRORS = {"permission_denied", "permission_required"}


def trace_metric_values(records: Iterable[TraceRecord]) -> dict[str, int | float | None]:
    materialized = tuple(records)
    model_turns = sum(record.kind == "model_turn_completed" for record in materialized)
    tool_records = [record for record in materialized if record.kind == "tool_result"]
    tool_errors = sum(not bool(record.payload.get("ok")) for record in tool_records)
    permission_denials = sum(
        record.payload.get("error_code") in _PERMISSION_ERRORS for record in tool_records
    )
    fingerprints = [
        (record.payload.get("tool_name"), record.payload.get("arguments_sha256"))
        for record in tool_records
    ]
    repeated = sum(max(0, count - 1) for count in Counter(fingerprints).values())

    context_records = [record for record in materialized if record.kind == "context_status"]
    context_before: int | None = None
    context_after: int | None = None
    if context_records:
        valid = [
            record
            for record in context_records
            if isinstance(record.payload.get("before_tokens"), int)
            and isinstance(record.payload.get("after_tokens"), int)
        ]
        if valid:
            selected = max(valid, key=lambda item: item.payload["before_tokens"])
            context_before = selected.payload["before_tokens"]
            context_after = selected.payload["after_tokens"]

    usage_records = [record for record in materialized if record.kind == "token_usage"]
    prompt_tokens = _sum_optional(usage_records, "prompt_tokens")
    completion_tokens = _sum_optional(usage_records, "completion_tokens")
    total_tokens = _sum_optional(usage_records, "total_tokens")
    duration = materialized[-1].elapsed_ms if materialized else 0
    return {
        "model_turns": model_turns,
        "tool_calls": len(tool_records),
        "tool_errors": tool_errors,
        "repeated_tool_calls": repeated,
        "permission_denials": permission_denials,
        "permission_overhead_proxy": permission_denials + tool_errors,
        "context_events": len(context_records),
        "context_before_tokens": context_before,
        "context_after_tokens": context_after,
        "context_tokens_saved": (
            max(0, context_before - context_after)
            if context_before is not None and context_after is not None
            else None
        ),
        "context_savings_rate": (
            max(0, context_before - context_after) / context_before
            if context_before is not None
            and context_after is not None
            and context_before > 0
            else None
        ),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "duration_ms": duration,
    }


def mcp_trace_metric_values(
    records: Iterable[TraceRecord],
) -> dict[str, int | float | None]:
    materialized = tuple(records)
    requests = [record for record in materialized if record.kind == "model_request"]
    tool_results = [record for record in materialized if record.kind == "tool_result"]
    definition_tokens = [
        record.payload.get("tool_definition_tokens") for record in requests
    ]
    definition_bytes = [
        record.payload.get("tool_definition_bytes") for record in requests
    ]
    valid_tokens = [
        value for value in definition_tokens if isinstance(value, int) and not isinstance(value, bool)
    ]
    valid_bytes = [
        value for value in definition_bytes if isinstance(value, int) and not isinstance(value, bool)
    ]
    usage = [record for record in materialized if record.kind == "token_usage"]
    return {
        "request_count": len(requests),
        "first_tool_definition_tokens": valid_tokens[0] if valid_tokens else None,
        "cumulative_tool_definition_tokens": sum(valid_tokens) if valid_tokens else None,
        "first_tool_definition_bytes": valid_bytes[0] if valid_bytes else None,
        "cumulative_tool_definition_bytes": sum(valid_bytes) if valid_bytes else None,
        "provider_prompt_tokens": _sum_optional(usage, "prompt_tokens"),
        "provider_completion_tokens": _sum_optional(usage, "completion_tokens"),
        "model_turns": sum(
            record.kind == "model_turn_completed" for record in materialized
        ),
        "tool_calls": len(tool_results),
        "search_calls": sum(
            record.payload.get("tool_name") == "mcp_search_tools"
            for record in tool_results
        ),
        "mcp_tool_calls": sum(
            isinstance(record.payload.get("tool_name"), str)
            and record.payload["tool_name"].startswith("mcp__")
            for record in tool_results
        ),
        "duration_ms": materialized[-1].elapsed_ms if materialized else 0,
    }


def build_attempt_metrics(
    records: Iterable[TraceRecord],
    verifications: Iterable[VerificationResult],
    *,
    passed: bool,
    judge: JudgeResult,
) -> AttemptMetrics:
    values = trace_metric_values(records)
    checked = tuple(verifications)
    verifier_rate = (
        sum(result.passed for result in checked) / len(checked) if checked else None
    )
    judge_score = judge.score if judge.status == JudgeStatus.AVAILABLE else None
    computed = "computed"
    observed = "observed"
    missing = "missing"
    return AttemptMetrics(
        passed=MetricValue(passed, computed),
        verifier_pass_rate=MetricValue(verifier_rate, computed if checked else missing),
        model_turns=MetricValue(values["model_turns"], computed),
        tool_calls=MetricValue(values["tool_calls"], computed),
        tool_errors=MetricValue(values["tool_errors"], computed),
        repeated_tool_calls=MetricValue(values["repeated_tool_calls"], computed),
        permission_denials=MetricValue(values["permission_denials"], computed),
        context_events=MetricValue(values["context_events"], computed),
        context_before_tokens=MetricValue(
            values["context_before_tokens"],
            observed if values["context_before_tokens"] is not None else missing,
        ),
        context_after_tokens=MetricValue(
            values["context_after_tokens"],
            observed if values["context_after_tokens"] is not None else missing,
        ),
        context_tokens_saved=MetricValue(
            values["context_tokens_saved"],
            computed if values["context_tokens_saved"] is not None else missing,
        ),
        prompt_tokens=MetricValue(
            values["prompt_tokens"], observed if values["prompt_tokens"] is not None else missing
        ),
        completion_tokens=MetricValue(
            values["completion_tokens"],
            observed if values["completion_tokens"] is not None else missing,
        ),
        total_tokens=MetricValue(
            values["total_tokens"], observed if values["total_tokens"] is not None else missing
        ),
        duration_ms=MetricValue(values["duration_ms"], observed),
        judge_score=MetricValue(
            judge_score,
            "judge" if judge_score is not None else missing,
        ),
        permission_overhead_proxy=MetricValue(
            values["permission_overhead_proxy"], computed
        ),
        context_savings_rate=MetricValue(
            values["context_savings_rate"],
            computed if values["context_savings_rate"] is not None else missing,
        ),
        permission_confirmations=MetricValue(None, "unavailable"),
    )


def _sum_optional(records: list[TraceRecord], field: str) -> int | None:
    values = [record.payload.get(field) for record in records]
    valid = [value for value in values if isinstance(value, int) and not isinstance(value, bool)]
    return sum(valid) if valid else None


__all__ = ["build_attempt_metrics", "mcp_trace_metric_values", "trace_metric_values"]
