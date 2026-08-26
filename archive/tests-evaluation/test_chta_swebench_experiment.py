from __future__ import annotations

from artcode.evaluation.chta.retention_probes import RetentionProbeResult
from artcode.evaluation.chta.swebench_experiment import (
    SWEbenchAttempt,
    SWEbenchExperimentRunner,
)


async def test_swebench_resolve_and_retention_denominators_stay_separate() -> None:
    instances = tuple(f"owner__repo-{index}" for index in range(6))

    async def attempt(profile, instance_id):
        resolved = profile == "candidate" or instance_id.endswith("0")
        return SWEbenchAttempt(
            profile,
            instance_id,
            resolved,
            f"patches/{profile}/{instance_id}.diff",
            f"traces/{profile}/{instance_id}.jsonl",
            f"official/{profile}/{instance_id}.log",
        )

    async def retention(profile, instance_id):
        count = 4 if profile == "candidate" else 2
        return tuple(
            RetentionProbeResult(
                instance_id,
                profile,
                f"{instance_id}:{index}",
                f"category-{index}",
                index < count,
                "a" * 64,
                "a" * 64 if index < count else None,
                "user" if profile == "candidate" else "system",
                f"retention/{profile}/{instance_id}.json",
            )
            for index in range(4)
        )

    result = await SWEbenchExperimentRunner(
        instances,
        baseline="baseline",
        candidate="candidate",
        attempt_executor=attempt,
        retention_executor=retention,
    ).run()

    assert result.status == "complete"
    assert result.profiles["baseline"] == {
        "resolved": 1,
        "gold_valid": 6,
        "resolve_rate": 1 / 6,
    }
    assert result.profiles["candidate"]["resolve_rate"] == 1.0
    assert result.retention["baseline"] == {
        "passed": 12,
        "total": 24,
        "retention_rate": 0.5,
    }
    assert result.retention["candidate"]["retention_rate"] == 1.0
