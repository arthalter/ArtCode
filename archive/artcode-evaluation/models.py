from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any


class AttemptStatus(StrEnum):
    PASSED = "passed"
    AGENT_FAILED = "agent_failed"
    TIMEOUT = "timeout"
    VERIFICATION_FAILED = "verification_failed"
    SETUP_FAILED = "setup_failed"
    CANCELLED = "cancelled"


class JudgeStatus(StrEnum):
    DISABLED = "disabled"
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class ChTAExperimentKind(StrEnum):
    MCP = "mcp"
    PERMISSION = "permission"
    SWEBENCH = "swebench"


@dataclass(frozen=True)
class VerifierSpec:
    id: str
    type: str
    required: bool = True
    path: str | None = None
    text: str | None = None
    argv: tuple[str, ...] = ()
    timeout_seconds: float | None = None
    event: str | None = None
    tool_name: str | None = None
    error_code: str | None = None
    context_status: str | None = None
    current_request_preserved: bool | None = None
    metric: str | None = None
    operator: str | None = None
    value: float | int | None = None


@dataclass(frozen=True)
class JudgeSpec:
    rubric: str
    minimum_score: int = 70


@dataclass(frozen=True)
class BenchmarkTask:
    id: str
    prompt: str
    fixture: Path
    repetitions: int
    timeout_seconds: float
    max_iterations: int
    permission_mode: str
    shell_policy: str
    mode: str
    tags: tuple[str, ...]
    verifiers: tuple[VerifierSpec, ...]
    judge: JudgeSpec | None = None


@dataclass(frozen=True)
class BenchmarkSpec:
    version: int
    name: str
    description: str
    source: Path
    fingerprint: str
    tasks: tuple[BenchmarkTask, ...]


@dataclass(frozen=True)
class ChTAModelSpec:
    provider: str
    name: str


@dataclass(frozen=True)
class ChTABudget:
    max_iterations: int
    max_output_tokens: int
    timeout_seconds: float


@dataclass(frozen=True)
class ChTARevisions:
    swebench_repository: str
    swebench_revision: str
    dataset: str
    dataset_revision: str
    split: str
    baseline_commit: str
    candidate_commit: str


@dataclass(frozen=True)
class ChTAProfile:
    id: str
    mechanism: str


@dataclass(frozen=True)
class ChTAExperiment:
    id: str
    kind: ChTAExperimentKind
    baseline: ChTAProfile
    candidate: ChTAProfile
    repetitions: int
    tasks: tuple[str, ...]
    parameters: dict[str, Any]


@dataclass(frozen=True)
class ChTAManifest:
    version: int
    name: str
    source: Path
    fingerprint: str
    model: ChTAModelSpec
    budget: ChTABudget
    revisions: ChTARevisions
    experiments: tuple[ChTAExperiment, ...]


@dataclass(frozen=True)
class TraceRecord:
    schema_version: int
    run_id: str
    task_id: str
    attempt: int
    sequence: int
    elapsed_ms: int
    kind: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class VerificationResult:
    id: str
    type: str
    required: bool
    passed: bool
    status: str
    duration_ms: int
    evidence: str = ""


@dataclass(frozen=True)
class JudgeCriterion:
    name: str
    score: int
    reason: str


@dataclass(frozen=True)
class JudgeResult:
    status: JudgeStatus
    score: int | None = None
    criteria: tuple[JudgeCriterion, ...] = ()
    summary: str = ""
    error: str = ""
    minimum_score: int | None = None
    meets_minimum: bool | None = None

    @classmethod
    def disabled(cls) -> "JudgeResult":
        return cls(JudgeStatus.DISABLED)

    @classmethod
    def unavailable(cls, error: str) -> "JudgeResult":
        return cls(JudgeStatus.UNAVAILABLE, error=error)


@dataclass(frozen=True)
class MetricValue:
    value: int | float | bool | None
    source: str


@dataclass(frozen=True)
class AttemptMetrics:
    passed: MetricValue
    verifier_pass_rate: MetricValue
    model_turns: MetricValue
    tool_calls: MetricValue
    tool_errors: MetricValue
    repeated_tool_calls: MetricValue
    permission_denials: MetricValue
    context_events: MetricValue
    context_before_tokens: MetricValue
    context_after_tokens: MetricValue
    context_tokens_saved: MetricValue
    prompt_tokens: MetricValue
    completion_tokens: MetricValue
    total_tokens: MetricValue
    duration_ms: MetricValue
    judge_score: MetricValue
    permission_overhead_proxy: MetricValue = field(
        default_factory=lambda: MetricValue(None, "missing")
    )
    context_savings_rate: MetricValue = field(
        default_factory=lambda: MetricValue(None, "missing")
    )
    permission_confirmations: MetricValue = field(
        default_factory=lambda: MetricValue(None, "unavailable")
    )


@dataclass(frozen=True)
class WorkspaceChange:
    path: str
    kind: str
    before_sha256: str | None = None
    after_sha256: str | None = None
    before_bytes: int | None = None
    after_bytes: int | None = None


@dataclass(frozen=True)
class AttemptResult:
    run_id: str
    task_id: str
    attempt: int
    status: AttemptStatus
    stop_reason: str | None
    final_response: str
    error: str
    workspace: str
    session_id: str | None
    trace_path: str
    attempt_path: str
    changes_path: str
    verifications: tuple[VerificationResult, ...]
    metrics: AttemptMetrics
    judge: JudgeResult = field(default_factory=JudgeResult.disabled)
    changes: tuple[WorkspaceChange, ...] = ()


def to_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return {key: to_jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, tuple):
        return [to_jsonable(item) for item in value]
    if isinstance(value, list):
        return [to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    return value


__all__ = [
    "AttemptMetrics",
    "AttemptResult",
    "AttemptStatus",
    "BenchmarkSpec",
    "BenchmarkTask",
    "ChTABudget",
    "ChTAExperiment",
    "ChTAExperimentKind",
    "ChTAManifest",
    "ChTAModelSpec",
    "ChTAProfile",
    "ChTARevisions",
    "JudgeCriterion",
    "JudgeResult",
    "JudgeSpec",
    "JudgeStatus",
    "MetricValue",
    "TraceRecord",
    "VerificationResult",
    "VerifierSpec",
    "WorkspaceChange",
    "to_jsonable",
]
