"""Public Skill Interface for discovery, activation, freezing, and isolation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable

from .agent import RunEvent, StopReason
from .model import Model, Usage
from .session import RunContribution, Session
from .tool import Tool
from .workspace import Workspace


class SkillSource(StrEnum):
    PROJECT = "project"
    USER = "user"
    BUILTIN = "builtin"
    EXTENSION = "extension"


class SkillMode(StrEnum):
    SHARED = "shared"
    ISOLATED = "isolated"


@dataclass(frozen=True, slots=True)
class SkillSummary:
    name: str
    description: str
    source: SkillSource
    mode: SkillMode


@dataclass(frozen=True, slots=True)
class SkillDiagnostic:
    name: str
    source: SkillSource
    message: str


@dataclass(frozen=True, slots=True)
class SkillSnapshot:
    skills: tuple[SkillSummary, ...]
    active: tuple[str, ...]
    diagnostics: tuple[SkillDiagnostic, ...]


@dataclass(frozen=True, slots=True)
class FrozenSkills:
    active: tuple[str, ...]
    contributions: tuple[RunContribution, ...]
    allowed_tools: frozenset[str] | None


@dataclass(frozen=True, slots=True)
class SkillActivation:
    name: str
    mode: SkillMode | None
    ok: bool
    message: str
    already_active: bool = False


@dataclass(frozen=True, slots=True)
class IsolatedSkillResult:
    summary: str
    stop_reason: StopReason
    usage: Usage
    events: tuple[RunEvent, ...]


@runtime_checkable
class Skill(Protocol):
    def refresh(self) -> SkillSnapshot: ...

    def select(self, text: str) -> SkillActivation: ...

    def activate(self, name: str) -> SkillActivation: ...

    def clear(self) -> SkillSnapshot: ...

    def snapshot(self) -> SkillSnapshot: ...

    def freeze(self) -> FrozenSkills: ...

    async def run_isolated(
        self,
        name: str,
        user_content: str,
        *,
        parent: Session,
        workspace: Workspace,
        model: Model,
        tools: Tool,
    ) -> IsolatedSkillResult: ...


__all__ = [
    "FrozenSkills",
    "IsolatedSkillResult",
    "Skill",
    "SkillActivation",
    "SkillDiagnostic",
    "SkillMode",
    "SkillSnapshot",
    "SkillSource",
    "SkillSummary",
]
