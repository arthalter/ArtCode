"""Frozen Run projection sources and committed continuation boundaries."""
from __future__ import annotations

from dataclasses import dataclass, field, replace

from artcode.core.model import ModelMessage, ModelRequest, ToolDefinition, Usage
from artcode.core.session import TranscriptFact, UserFact
from artcode.core.tool import ToolRun

from .prompt import project_facts, summary_message


@dataclass(frozen=True, slots=True)
class FrozenProjection:
    prefix: tuple[ModelMessage, ...]
    template: ModelRequest
    parent_prefix_size: int = 0

    def render(
        self,
        facts: tuple[TranscriptFact, ...],
        tools: ToolRun,
        summary: str | None,
        through: int,
    ) -> ModelRequest:
        derived = (summary_message(summary, through),) if summary else ()
        return replace(
            self.template,
            prompt=(*self.prefix, *derived, *project_facts(facts, through)),
            tools=tuple(ToolDefinition(item.name, item.description, item.parameters_json) for item in tools.descriptors),
        )


@dataclass(slots=True)
class RunProjection:
    frozen: FrozenProjection
    facts: tuple[TranscriptFact, ...]
    cursor: int
    fact_offset: int
    summary: str | None
    summary_through: int
    request: ModelRequest
    attempted: set[int] = field(default_factory=set)
    unsuccessful_attempts: int = 0
    last_usage: Usage | None = None
    usage_adjustment: int | None = None

    def accept(self, request: ModelRequest, committed: tuple[TranscriptFact, ...]) -> None:
        """Only append complete facts already committed by this Run's caller."""
        previous = self.request.prompt
        if request.prompt[:len(previous)] != previous:
            raise ValueError("后续请求必须保留上一次准备的完整 Prompt 前缀。")
        suffix = request.prompt[len(previous):]
        accepted: list[TranscriptFact] = []
        cursor = self.cursor
        while suffix:
            if cursor >= len(committed) or isinstance(committed[cursor], UserFact):
                raise ValueError("后续请求只能投影当前 Run 已提交的完整事实。")
            fact = committed[cursor]
            messages = project_facts((fact,), 0)
            if suffix[:len(messages)] != messages:
                raise ValueError("后续请求与已提交 Transcript 事实不一致。")
            accepted.append(fact)
            suffix = suffix[len(messages):]
            cursor += 1
        self.facts = (*self.facts, *accepted)
        self.cursor = cursor
        self.request = request
