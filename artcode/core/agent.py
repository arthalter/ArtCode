"""Public Agent Interface and observable Run events."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, TypeAlias, runtime_checkable

from .model import Model, ToolRequest, Usage
from .session import DispatchedRun, Session
from .tool import Approver, Tool, ToolResult


class StopReason(StrEnum):
    NATURAL = "natural"
    LIMIT = "limit"
    CANCELLED = "cancelled"
    MODEL_FAILURE = "model_failure"
    LENGTH = "length"
    CANNOT_CONTINUE = "cannot_continue"


class RunControl:
    def __init__(self) -> None:
        self._cancelled = asyncio.Event()

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    def cancel(self) -> None:
        self._cancelled.set()

    async def wait_cancelled(self) -> None:
        await self._cancelled.wait()


@dataclass(frozen=True, slots=True)
class RunOutcome:
    stop_reason: StopReason
    rounds: int
    usage: Usage
    final_text: str = ""
    tool_batches: int = 0
    detail: str = ""


@dataclass(frozen=True, slots=True)
class RunStarted:
    run_id: str


@dataclass(frozen=True, slots=True)
class TextEvent:
    text: str


@dataclass(frozen=True, slots=True)
class UsageEvent:
    usage: Usage


@dataclass(frozen=True, slots=True)
class ToolBatchEvent:
    requests: tuple[ToolRequest, ...]
    results: tuple[ToolResult, ...]


@dataclass(frozen=True, slots=True)
class RunError:
    category: str
    message: str


@dataclass(frozen=True, slots=True)
class RunFinished:
    outcome: RunOutcome


RunEvent: TypeAlias = RunStarted | TextEvent | UsageEvent | ToolBatchEvent | RunError | RunFinished


@runtime_checkable
class Agent(Protocol):
    def run(
        self,
        dispatched: DispatchedRun,
        *,
        max_rounds: int | None = None,
        control: RunControl | None = None,
    ) -> AsyncIterator[RunEvent]: ...


__all__ = [
    "Agent",
    "RunControl",
    "RunError",
    "RunEvent",
    "RunFinished",
    "RunOutcome",
    "RunStarted",
    "StopReason",
    "TextEvent",
    "ToolBatchEvent",
    "UsageEvent",
]
