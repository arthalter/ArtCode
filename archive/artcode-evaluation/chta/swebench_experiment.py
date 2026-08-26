from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from .retention_probes import RetentionProbeResult, aggregate_retention


@dataclass(frozen=True)
class SWEbenchAttempt:
    profile: str
    instance_id: str
    resolved: bool
    patch_path: str
    trace_path: str
    official_log_path: str
    error: str = ""


@dataclass(frozen=True)
class SWEbenchExperimentResult:
    status: str
    gold_valid_instances: tuple[str, ...]
    attempts: tuple[SWEbenchAttempt, ...]
    profiles: dict[str, dict[str, int | float | None]]
    retention: dict[str, dict[str, int | float | None]]
    retention_probes: tuple[RetentionProbeResult, ...]


AttemptExecutor = Callable[[str, str], Awaitable[SWEbenchAttempt]]
RetentionExecutor = Callable[[str, str], Awaitable[tuple[RetentionProbeResult, ...]]]


class SWEbenchExperimentRunner:
    def __init__(
        self,
        locked_instances: tuple[str, ...],
        *,
        baseline: str,
        candidate: str,
        attempt_executor: AttemptExecutor,
        retention_executor: RetentionExecutor,
    ) -> None:
        if len(locked_instances) != 6 or len(set(locked_instances)) != 6:
            raise ValueError("SWE-bench-Live pilot 必须锁定 6 个唯一 gold-valid 实例")
        self.instances = locked_instances
        self.profiles = (baseline, candidate)
        self.attempt_executor = attempt_executor
        self.retention_executor = retention_executor

    async def run(self) -> SWEbenchExperimentResult:
        attempts = []
        probes = []
        for profile in self.profiles:
            for instance_id in self.instances:
                try:
                    attempt = await self.attempt_executor(profile, instance_id)
                except Exception as exc:
                    attempt = SWEbenchAttempt(
                        profile,
                        instance_id,
                        False,
                        "",
                        "",
                        "",
                        f"{type(exc).__name__}: {exc}",
                    )
                if attempt.profile != profile or attempt.instance_id != instance_id:
                    raise ValueError("SWE-bench executor 返回了不匹配的 Attempt 身份")
                attempts.append(attempt)
                try:
                    selected = await self.retention_executor(profile, instance_id)
                except Exception:
                    selected = ()
                probes.extend(selected)

        profile_values = {}
        retention_values = {}
        for profile in self.profiles:
            selected = [item for item in attempts if item.profile == profile]
            resolved = sum(item.resolved for item in selected)
            profile_values[profile] = {
                "resolved": resolved,
                "gold_valid": len(self.instances),
                "resolve_rate": resolved / len(self.instances),
            }
            aggregate = aggregate_retention(profile, tuple(probes))
            retention_values[profile] = {
                "passed": aggregate.passed,
                "total": aggregate.total,
                "retention_rate": aggregate.rate,
            }
        expected_attempts = 2 * len(self.instances)
        expected_probes = expected_attempts * 4
        status = (
            "complete"
            if len(attempts) == expected_attempts and len(probes) == expected_probes
            else "partial"
        )
        return SWEbenchExperimentResult(
            status,
            self.instances,
            tuple(attempts),
            profile_values,
            retention_values,
            tuple(probes),
        )


__all__ = ["SWEbenchAttempt", "SWEbenchExperimentResult", "SWEbenchExperimentRunner"]
