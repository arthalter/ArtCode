from __future__ import annotations

from collections.abc import Awaitable, Callable
from copy import deepcopy
from dataclasses import dataclass
from statistics import median, pstdev
from typing import Any

from artcode.evaluation.metrics import mcp_trace_metric_values
from artcode.evaluation.models import ChTAExperiment, ChTAExperimentKind, TraceRecord


@dataclass(frozen=True)
class McpAttemptObservation:
    profile: str
    task_id: str
    repetition: int
    success: bool
    trace: tuple[TraceRecord, ...]
    evidence_path: str
    error: str = ""


@dataclass(frozen=True)
class McpExperimentResult:
    experiment_id: str
    status: str
    attempts: tuple[dict[str, Any], ...]
    profiles: dict[str, dict[str, Any]]
    comparisons: dict[str, dict[str, int | float | None]]


AttemptExecutor = Callable[
    [str, str, int], Awaitable[McpAttemptObservation]
]


class McpExperimentRunner:
    def __init__(
        self,
        experiment: ChTAExperiment,
        executor: AttemptExecutor,
    ) -> None:
        if experiment.kind is not ChTAExperimentKind.MCP:
            raise ValueError("McpExperimentRunner 只能运行 mcp 实验")
        if experiment.parameters.get("target_task_count") != len(experiment.tasks):
            raise ValueError("MCP task 数与 target_task_count 不一致")
        self.experiment = experiment
        self.executor = executor

    async def run(self) -> McpExperimentResult:
        observations: list[McpAttemptObservation] = []
        profiles = (self.experiment.baseline.id, self.experiment.candidate.id)
        for profile in profiles:
            for task_id in self.experiment.tasks:
                for repetition in range(1, self.experiment.repetitions + 1):
                    try:
                        observation = await self.executor(profile, task_id, repetition)
                    except Exception as exc:
                        observation = McpAttemptObservation(
                            profile,
                            task_id,
                            repetition,
                            False,
                            (),
                            "",
                            f"{type(exc).__name__}: {exc}",
                        )
                    if (
                        observation.profile != profile
                        or observation.task_id != task_id
                        or observation.repetition != repetition
                    ):
                        raise ValueError("MCP executor 返回了不匹配的 Attempt 身份")
                    observations.append(observation)

        attempts = tuple(_attempt_payload(item) for item in observations)
        aggregates = {
            profile: _aggregate(
                [item for item in attempts if item["profile"] == profile]
            )
            for profile in profiles
        }
        comparisons = _comparisons(
            aggregates[self.experiment.baseline.id],
            aggregates[self.experiment.candidate.id],
        )
        expected = len(profiles) * len(self.experiment.tasks) * self.experiment.repetitions
        status = "complete" if len(attempts) == expected else "partial"
        return McpExperimentResult(
            self.experiment.id,
            status,
            attempts,
            aggregates,
            comparisons,
        )


def _attempt_payload(observation: McpAttemptObservation) -> dict[str, Any]:
    return {
        "profile": observation.profile,
        "task_id": observation.task_id,
        "repetition": observation.repetition,
        "success": observation.success,
        "metrics": mcp_trace_metric_values(observation.trace),
        "evidence_path": observation.evidence_path,
        "error": observation.error,
    }


def _aggregate(attempts: list[dict[str, Any]]) -> dict[str, Any]:
    metric_names = (
        "first_tool_definition_tokens",
        "cumulative_tool_definition_tokens",
        "provider_prompt_tokens",
        "model_turns",
        "tool_calls",
        "search_calls",
        "mcp_tool_calls",
        "duration_ms",
    )
    metrics: dict[str, dict[str, int | float | None]] = {}
    for name in metric_names:
        values = [item["metrics"][name] for item in attempts]
        numeric = [
            value
            for value in values
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        ]
        metrics[name] = {
            "available": len(numeric),
            "total": sum(numeric) if numeric else None,
            "mean": sum(numeric) / len(numeric) if numeric else None,
            "median": median(numeric) if numeric else None,
            "pstdev": pstdev(numeric) if numeric else None,
            "minimum": min(numeric) if numeric else None,
            "maximum": max(numeric) if numeric else None,
        }
    successes = sum(bool(item["success"]) for item in attempts)
    return {
        "attempt_count": len(attempts),
        "success_count": successes,
        "success_rate": successes / len(attempts) if attempts else None,
        "metrics": metrics,
    }


def _comparisons(
    baseline: dict[str, Any], candidate: dict[str, Any]
) -> dict[str, dict[str, int | float | None]]:
    result: dict[str, dict[str, int | float | None]] = {}
    for name in (
        "first_tool_definition_tokens",
        "cumulative_tool_definition_tokens",
        "provider_prompt_tokens",
    ):
        baseline_total = baseline["metrics"][name]["total"]
        candidate_total = candidate["metrics"][name]["total"]
        reduction = (
            (baseline_total - candidate_total) / baseline_total
            if isinstance(baseline_total, (int, float))
            and baseline_total > 0
            and isinstance(candidate_total, (int, float))
            else None
        )
        result[name] = {
            "baseline": baseline_total,
            "candidate": candidate_total,
            "reduction_rate": reduction,
        }
    result["success_rate"] = {
        "baseline": baseline["success_rate"],
        "candidate": candidate["success_rate"],
        "reduction_rate": None,
    }
    return result


def reaggregate_mcp_payload(
    payload: dict[str, Any],
    *,
    baseline: str = "eager",
    candidate: str = "lazy",
) -> dict[str, Any]:
    """Rebuild aggregates from immutable attempt rows for report regeneration."""

    attempts = payload.get("attempts")
    if not isinstance(attempts, list):
        raise ValueError("MCP 结果缺少 attempts 列表")
    result = deepcopy(payload)
    aggregates = {
        profile: _aggregate(
            [item for item in attempts if item.get("profile") == profile]
        )
        for profile in (baseline, candidate)
    }
    result["profiles"] = aggregates
    result["comparisons"] = _comparisons(aggregates[baseline], aggregates[candidate])
    return result


__all__ = [
    "McpAttemptObservation",
    "McpExperimentResult",
    "McpExperimentRunner",
    "reaggregate_mcp_payload",
]
