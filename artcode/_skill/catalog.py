from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from artcode.core.model import Model
from artcode.core.session import RunContribution, Session
from artcode.core.skill import (
    FrozenSkills,
    IsolatedSkillResult,
    SkillActivation,
    SkillDiagnostic,
    SkillMode,
    SkillSnapshot,
)
from artcode.core.tool import Tool
from artcode.core.workspace import Workspace

from .discovery import Discovery, discover
from .execution import run_isolated
from .parsing import LoadedSkill, SkillCandidate, load_skill


class LocalSkills:
    def __init__(
        self,
        project_root: Path,
        user_root: Path,
        builtin_root: Path,
        *,
        extension_roots: tuple[Path, ...] = (),
        known_tools: Callable[[], set[str] | frozenset[str]],
        available_models: Callable[[], set[str] | frozenset[str]] | None = None,
    ) -> None:
        self.project_root = project_root
        self.user_root = user_root
        self.builtin_root = builtin_root
        self.extension_roots = extension_roots
        self.known_tools = known_tools
        self.available_models = available_models
        self._discovery = Discovery((), (), ())
        self._active: dict[str, LoadedSkill] = {}
        self._diagnostics: tuple[SkillDiagnostic, ...] = ()

    def refresh(self) -> SkillSnapshot:
        found = discover(
            self.project_root,
            self.user_root,
            self.builtin_root,
            self.extension_roots,
        )
        diagnostics = list(found.diagnostics)
        candidates = {item.metadata.name: item for item in found.candidates}
        for name, current in tuple(self._active.items()):
            candidate = candidates.get(name)
            if candidate is None:
                diagnostics.append(
                    SkillDiagnostic(name, current.candidate.source, "已激活 Skill 的新版本不可用；保留最后有效版本。")
                )
                continue
            try:
                updated = self._load_valid(candidate)
            except ValueError as exc:
                diagnostics.append(
                    SkillDiagnostic(name, candidate.source, f"Skill 热更新无效；保留最后有效版本：{exc}")
                )
            else:
                self._active[name] = updated
        self._discovery = found
        self._diagnostics = tuple(diagnostics)
        return self.snapshot()

    def select(self, text: str) -> SkillActivation:
        self.refresh()
        if not isinstance(text, str):
            return SkillActivation("", None, False, "Skill 选择文本无效。")
        lowered = text.casefold()
        matches = [item.name for item in self._discovery.summaries if item.name.casefold() in lowered]
        if len(matches) != 1:
            return SkillActivation("", None, False, "未能唯一选择 Skill。")
        return self.activate(matches[0])

    def activate(self, name: str) -> SkillActivation:
        self.refresh()
        normalized = name.strip().casefold() if isinstance(name, str) else ""
        current = self._active.get(normalized)
        if current is not None:
            return SkillActivation(normalized, current.candidate.metadata.mode, True, f"Skill 已激活：{normalized}", True)
        candidate = next(
            (item for item in self._discovery.candidates if item.metadata.name == normalized),
            None,
        )
        if candidate is None:
            return SkillActivation(normalized, None, False, f"未找到可用 Skill：{normalized}")
        try:
            loaded = self._load_valid(candidate)
        except ValueError as exc:
            return SkillActivation(normalized, candidate.metadata.mode, False, str(exc))
        self._active[normalized] = loaded
        return SkillActivation(normalized, loaded.candidate.metadata.mode, True, f"已激活 Skill：{normalized}")

    def clear(self) -> SkillSnapshot:
        self._active.clear()
        return self.snapshot()

    def snapshot(self) -> SkillSnapshot:
        return SkillSnapshot(
            self._discovery.summaries,
            tuple(self._active),
            self._diagnostics,
        )

    def freeze(self) -> FrozenSkills:
        self.refresh()
        active = tuple(self._active.values())
        allowed = None
        if active:
            allowed = frozenset.intersection(
                *(frozenset(item.candidate.metadata.tools) for item in active)
            )
        contributions = tuple(
            RunContribution(item.name, item.sop, item.candidate.metadata.model)
            for item in active
        )
        return FrozenSkills(tuple(item.name for item in active), contributions, allowed)

    async def run_isolated(
        self,
        name: str,
        user_content: str,
        *,
        parent: Session,
        workspace: Workspace,
        model: Model,
        tools: Tool,
    ) -> IsolatedSkillResult:
        frozen = self.freeze()
        definition = self._active.get(name)
        if definition is None:
            raise ValueError(f"Skill 未激活：{name}")
        if definition.candidate.metadata.mode is not SkillMode.ISOLATED:
            raise ValueError(f"Skill {name} 不是 isolated 模式。")
        return await run_isolated(
            definition,
            user_content,
            parent=parent,
            workspace=workspace,
            model=model,
            tools=tools,
            allowed_tools=frozen.allowed_tools or frozenset(),
        )

    def _load_valid(self, candidate: SkillCandidate) -> LoadedSkill:
        loaded = load_skill(candidate)
        unknown = set(loaded.candidate.metadata.tools) - set(self.known_tools())
        if unknown:
            raise ValueError(f"Skill 引用了未知 Tool：{', '.join(sorted(unknown))}")
        model = loaded.candidate.metadata.model
        if model is not None and self.available_models is not None and model not in self.available_models():
            raise ValueError(f"Skill 指定的模型不可用：{model}")
        return loaded
