from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class SkillSource(StrEnum):
    PROJECT = "project"
    USER = "user"
    BUILTIN = "builtin"


class SkillMode(StrEnum):
    SHARED = "shared"
    ISOLATED = "isolated"


@dataclass(frozen=True)
class SkillDiagnostic:
    path: Path
    message: str
    source: SkillSource
    blocking: bool = False

    def render(self) -> str:
        return f"{self.path}：{self.message}"


@dataclass(frozen=True)
class SkillMetadata:
    name: str
    description: str
    tools: tuple[str, ...]
    mode: SkillMode
    history_turns: int
    model: str | None = None


@dataclass(frozen=True)
class SkillDefinition:
    metadata: SkillMetadata
    source: SkillSource
    entry_path: Path
    package_root: Path
    sop: str
    resources: tuple[Path, ...]
    fingerprint: str

    @property
    def name(self) -> str:
        return self.metadata.name


@dataclass(frozen=True)
class SkillCatalog:
    definitions: tuple[SkillDefinition, ...]
    diagnostics: tuple[SkillDiagnostic, ...] = ()

    def get(self, name: str) -> SkillDefinition | None:
        normalized = name.strip().lower()
        return next((item for item in self.definitions if item.name == normalized), None)

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(item.name for item in self.definitions)


@dataclass(frozen=True)
class ActiveSkill:
    definition: SkillDefinition
    order: int


@dataclass(frozen=True)
class SkillRunSnapshot:
    catalog: SkillCatalog
    active: tuple[ActiveSkill, ...]
    allowed_tool_names: frozenset[str] | None

    @property
    def active_definitions(self) -> tuple[SkillDefinition, ...]:
        return tuple(item.definition for item in self.active)


@dataclass(frozen=True)
class SkillActivationResult:
    definition: SkillDefinition | None
    message: str
    already_active: bool = False

    @property
    def ok(self) -> bool:
        return self.definition is not None
