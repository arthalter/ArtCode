from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


SINGLE_TOOL_RESULT_TOKENS = 8_000
AGGREGATE_TOOL_RESULT_TOKENS = 16_000
ARTIFACT_PREVIEW_BYTES = 2_048
RECENT_HISTORY_TOKENS = 10_000
RECENT_MINIMUM_MESSAGES = 5
SUMMARY_MAX_OUTPUT_TOKENS = 20_000
AUTOMATIC_FAILURE_LIMIT = 3


class CompressionTrigger(StrEnum):
    AUTOMATIC = "automatic"
    FORCED = "forced"
    MANUAL = "manual"
    EMERGENCY = "emergency"
    RESTORE = "restore"


@dataclass
class CompressionCircuit:
    consecutive_failures: int = 0
    open: bool = False
    forced_attempted: bool = False

    def reset(self) -> None:
        self.consecutive_failures = 0
        self.open = False
        self.forced_attempted = False


@dataclass(frozen=True)
class TokenAnchor:
    prompt_tokens: int
    heuristic_tokens: int


@dataclass(frozen=True)
class PersistenceFailure:
    entry_id: str
    message: str


@dataclass(frozen=True)
class LightweightReport:
    persisted_count: int = 0
    before_tokens: int = 0
    after_tokens: int = 0
    failures: tuple[PersistenceFailure, ...] = ()


@dataclass(frozen=True)
class CompressionReport:
    trigger: CompressionTrigger
    status: str
    before_tokens: int
    after_tokens: int
    persisted_count: int = 0
    circuit_open: bool = False
    message: str = ""
