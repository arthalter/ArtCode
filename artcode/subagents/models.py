from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from artcode.permissions import PermissionMode
from artcode.providers.events import TokenUsage


class AgentKind(StrEnum):
    DEFINITION = "definition"
    FORK = "fork"


class RoleSource(StrEnum):
    PROJECT = "project"
    USER = "user"
    BUILTIN = "builtin"
    PLUGIN = "plugin"


class IsolationMode(StrEnum):
    NONE = "none"
    WORKTREE = "worktree"


class SubagentStopReason(StrEnum):
    NATURAL = "natural"
    FAILED = "failed"
    MAX_ROUNDS = "max_rounds"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class UsageTotals:
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    cached_tokens: int | None = None
    cache_miss_tokens: int | None = None
    reported_rounds: int = 0

    @classmethod
    def empty(cls) -> "UsageTotals":
        return cls()

    def add(self, usage: TokenUsage | None) -> "UsageTotals":
        if usage is None:
            return self
        def total(left: int | None, right: int | None) -> int | None:
            if self.reported_rounds == 0:
                return right
            if left is None or right is None:
                return None
            return left + right
        return UsageTotals(
            total(self.prompt_tokens, usage.prompt_tokens),
            total(self.completion_tokens, usage.completion_tokens),
            total(self.total_tokens, usage.total_tokens),
            total(self.cached_tokens, usage.cached_tokens),
            total(self.cache_miss_tokens, usage.cache_miss_tokens),
            self.reported_rounds + 1,
        )

    def to_dict(self) -> dict[str, int | None]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "cached_tokens": self.cached_tokens,
            "cache_miss_tokens": self.cache_miss_tokens,
        }


@dataclass(frozen=True)
class RoleDefinition:
    name: str
    description: str
    system_prompt: str
    source: RoleSource
    path: Path
    tool_allow: frozenset[str]
    tool_deny: frozenset[str]
    model_tier: str
    max_rounds: int
    permission_mode: PermissionMode
    isolation: IsolationMode

    def __post_init__(self) -> None:
        if not self.name or self.name != self.name.strip():
            raise ValueError("role name must be non-empty")
        if not self.description.strip() or not self.system_prompt.strip():
            raise ValueError("role description and system prompt must be non-empty")
        if self.tool_allow & self.tool_deny:
            raise ValueError("role tool allow/deny entries cannot overlap")
        if not 1 <= self.max_rounds <= 100:
            raise ValueError("role max_rounds must be in 1..100")
        if self.model_tier not in {"inherit", "haiku", "sonnet", "opus"}:
            raise ValueError("invalid role model tier")

    @property
    def worktree(self) -> bool:
        return self.isolation is IsolationMode.WORKTREE


@dataclass(frozen=True)
class AgentCreateRequest:
    kind: AgentKind
    task: str
    role_name: str | None = None
    background: bool | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, AgentKind):
            raise TypeError("kind must be AgentKind")
        if not isinstance(self.task, str):
            raise ValueError("task must be a string")
        task = self.task.strip()
        if not 1 <= len(task) <= 20_000:
            raise ValueError("task length must be between 1 and 20000 Unicode characters")
        object.__setattr__(self, "task", task)
        if self.role_name is not None and (not isinstance(self.role_name, str) or not self.role_name.strip()):
            raise ValueError("role_name must be a non-empty string or None")
        if self.role_name is not None:
            object.__setattr__(self, "role_name", self.role_name.strip())
        if self.background is not None and not isinstance(self.background, bool):
            raise TypeError("background must be a boolean or omitted")
        if self.kind is AgentKind.DEFINITION and self.role_name is None:
            raise ValueError("definition subagents require a role")
        if self.kind is AgentKind.DEFINITION:
            object.__setattr__(self, "background", bool(self.background))
        elif self.background is False:
            raise ValueError("fork subagents cannot set background to false")
        else:
            object.__setattr__(self, "background", True)


@dataclass(frozen=True)
class PermissionEvent:
    task_id: str
    tool_name: str
    decision: str
    source: str
    target_summary: str
    timestamp: float


@dataclass(frozen=True)
class SubagentResult:
    task_id: str
    stop_reason: SubagentStopReason
    final_text: str
    rounds: int
    usage: UsageTotals = field(default_factory=UsageTotals.empty)
    permission_events: tuple[PermissionEvent, ...] = ()
    handoff: object | None = None
    error_message: str = ""
    cache_prefix_preserved: bool | None = None

    def __post_init__(self) -> None:
        if self.rounds < 0:
            raise ValueError("rounds cannot be negative")
