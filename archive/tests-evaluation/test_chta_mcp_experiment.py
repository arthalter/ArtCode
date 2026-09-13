from __future__ import annotations

from pathlib import Path

import pytest

from artcode.evaluation.chta.mcp_experiment import (
    McpAttemptObservation,
    McpExperimentRunner,
    reaggregate_mcp_payload,
)
from artcode.evaluation.manifest import load_chta_manifest
from artcode.evaluation.models import TraceRecord


ROOT = Path(__file__).resolve().parents[2]


def _record(sequence: int, kind: str, payload: dict, elapsed: int = 10) -> TraceRecord:
    return TraceRecord(1, "run", "task", 1, sequence, elapsed, kind, payload)


async def test_mcp_runner_preserves_full_matrix_and_raw_reduction_counts() -> None:
    manifest = load_chta_manifest(ROOT / "benchmarks" / "chTA" / "manifest.yml")
    experiment = next(item for item in manifest.experiments if item.kind.value == "mcp")

    async def execute(profile: str, task_id: str, repetition: int):
        eager = profile == "eager"
        success = not (profile == "lazy" and task_id == experiment.tasks[-1] and repetition == 3)
        trace = (
            _record(
                1,
                "model_request",
                {
                    "tool_definition_tokens": 1000 if eager else 100,
                    "tool_definition_bytes": 4000 if eager else 400,
                },
            ),
            _record(
                2,
                "tool_result",
                {"tool_name": "mcp_search_tools" if not eager else "mcp__fixture__target"},
            ),
            _record(
                3,
                "token_usage",
                {"prompt_tokens": 1500 if eager else 700, "completion_tokens": 20},
            ),
            _record(4, "model_turn_completed", {}, 50),
        )
        return McpAttemptObservation(
            profile,
            task_id,
            repetition,
            success,
            trace,
            f"traces/{profile}/{task_id}/{repetition}.jsonl",
        )

    result = await McpExperimentRunner(experiment, execute).run()

    assert result.status == "complete"
    assert len(result.attempts) == 30
    assert result.profiles["eager"]["success_count"] == 15
    assert result.profiles["lazy"]["success_count"] == 14
    token = result.comparisons["first_tool_definition_tokens"]
    assert token["baseline"] == 15000
    assert token["candidate"] == 1500
    assert token["reduction_rate"] == pytest.approx(0.9)
    assert result.comparisons["provider_prompt_tokens"]["reduction_rate"] == pytest.approx(
        (22500 - 10500) / 22500
    )


async def test_mcp_runner_records_executor_failure_in_success_denominator() -> None:
    manifest = load_chta_manifest(ROOT / "benchmarks" / "chTA" / "manifest.yml")
    experiment = next(item for item in manifest.experiments if item.kind.value == "mcp")

    async def execute(profile: str, task_id: str, repetition: int):
        if profile == "lazy" and repetition == 1:
            raise RuntimeError("controlled")
        return McpAttemptObservation(profile, task_id, repetition, True, (), "trace")

    result = await McpExperimentRunner(experiment, execute).run()
    assert result.profiles["lazy"]["attempt_count"] == 15
    assert result.profiles["lazy"]["success_count"] == 10
    assert sum(bool(item["error"]) for item in result.attempts) == 5


def test_mcp_reaggregation_adds_median_and_dispersion() -> None:
    attempts = [
        {
            "profile": profile,
            "success": True,
            "metrics": {
                "first_tool_definition_tokens": value,
                "cumulative_tool_definition_tokens": value * 2,
                "provider_prompt_tokens": value * 3,
                "model_turns": 2,
                "tool_calls": 1,
                "search_calls": 0,
                "mcp_tool_calls": 1,
                "duration_ms": value,
            },
        }
        for profile, value in (
            ("eager", 100),
            ("eager", 200),
            ("lazy", 10),
            ("lazy", 20),
        )
    ]

    result = reaggregate_mcp_payload({"attempts": attempts})

    metrics = result["profiles"]["eager"]["metrics"][
        "first_tool_definition_tokens"
    ]
    assert metrics["median"] == 150
    assert metrics["pstdev"] == 50
    assert result["comparisons"]["first_tool_definition_tokens"][
        "reduction_rate"
    ] == pytest.approx(0.9)
