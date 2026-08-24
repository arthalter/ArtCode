from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from .discovery import SkillDiscovery, SkillRoots
from .models import (
    ActiveSkill,
    SkillActivationResult,
    SkillCatalog,
    SkillDefinition,
    SkillDiagnostic,
    SkillRunSnapshot,
)


class SkillStartupError(ValueError):
    pass


class SkillService:
    """Owns the current catalog and the session-local active Skill snapshots."""

    def __init__(
        self,
        roots: SkillRoots,
        *,
        known_tool_names: set[str] | frozenset[str],
        reserved_commands: set[str] | frozenset[str] = frozenset(),
    ) -> None:
        self.discovery = SkillDiscovery(roots)
        self.known_tool_names = frozenset(known_tool_names)
        self.reserved_commands = frozenset(item.lower() for item in reserved_commands)
        self._catalog = SkillCatalog(())
        self._active: dict[str, ActiveSkill] = {}
        self._next_order = 1
        self._started = False
        self._pending_model_override: str | None = None
        self._reported_diagnostics: set[tuple[str, str]] = set()

    @classmethod
    def from_paths(
        cls,
        project_root: Path,
        user_root: Path,
        builtin_root: Path,
        *,
        known_tool_names: set[str] | frozenset[str],
        reserved_commands: set[str] | frozenset[str] = frozenset(),
    ) -> "SkillService":
        return cls(
            SkillRoots(project_root, user_root, builtin_root),
            known_tool_names=known_tool_names,
            reserved_commands=reserved_commands,
        )

    @property
    def catalog(self) -> SkillCatalog:
        return self._catalog

    @property
    def diagnostics(self) -> tuple[SkillDiagnostic, ...]:
        return self._catalog.diagnostics

    def start(self) -> None:
        catalog = self.discovery.discover()
        errors = self._startup_errors(catalog)
        if errors:
            raise SkillStartupError("\n".join(item.render() for item in errors))
        self._catalog = self._filter_command_conflicts(catalog)
        self._started = True

    def refresh(self) -> SkillRunSnapshot:
        if not self._started:
            self.start()
        discovered = self.discovery.discover()
        refreshed = self._filter_command_conflicts(discovered)
        invalid_names = {
            item.name
            for item in discovered.definitions
            if self._unknown_tool_names(item)
        }
        valid_definitions = tuple(
            item for item in refreshed.definitions if item.name not in invalid_names
        )
        diagnostics = list(refreshed.diagnostics)
        for definition in discovered.definitions:
            unknown = self._unknown_tool_names(definition)
            if unknown:
                diagnostics.append(
                    SkillDiagnostic(
                        definition.entry_path,
                        f"Skill tools 包含未知普通工具：{', '.join(unknown)}。",
                        definition.source,
                    )
                )
        self._catalog = SkillCatalog(
            valid_definitions,
            tuple(sorted(diagnostics, key=lambda item: (str(item.path), item.message))),
        )
        current = {item.name: item for item in self._catalog.definitions}
        retained: dict[str, ActiveSkill] = {}
        for name, active in self._active.items():
            updated = current.get(name)
            if updated is not None:
                retained[name] = replace(active, definition=updated)
            else:
                retained[name] = active
                diagnostics.append(
                    SkillDiagnostic(
                        active.definition.entry_path,
                        f"已激活 Skill {name!r} 的新版本不可用或已删除；当前会话保留最后有效版本。",
                        active.definition.source,
                    )
                )
        self._active = retained
        if len(diagnostics) != len(self._catalog.diagnostics):
            self._catalog = SkillCatalog(
                self._catalog.definitions,
                tuple(sorted(diagnostics, key=lambda item: (str(item.path), item.message))),
            )
        return self.snapshot()

    def activate(
        self,
        name: str,
        *,
        for_model_execution: bool = False,
    ) -> SkillActivationResult:
        self.refresh()
        definition = self._catalog.get(name)
        if definition is None:
            return SkillActivationResult(None, f"未找到可用 Skill：{name}。")
        current = self._active.get(definition.name)
        if current is not None:
            if for_model_execution:
                self._pending_model_override = current.definition.metadata.model
            return SkillActivationResult(current.definition, f"Skill 已处于激活状态：{definition.name}。", True)
        self._active[definition.name] = ActiveSkill(definition, self._next_order)
        self._next_order += 1
        if for_model_execution:
            self._pending_model_override = definition.metadata.model
        return SkillActivationResult(definition, f"已激活 Skill：{definition.name}。")

    def clear(self) -> None:
        self._active.clear()
        self._next_order = 1
        self._pending_model_override = None

    def consume_model_override(self) -> str | None:
        value = self._pending_model_override
        self._pending_model_override = None
        return value

    def take_unreported_diagnostics(self) -> tuple[SkillDiagnostic, ...]:
        result: list[SkillDiagnostic] = []
        for diagnostic in self._catalog.diagnostics:
            key = (str(diagnostic.path), diagnostic.message)
            if key not in self._reported_diagnostics:
                self._reported_diagnostics.add(key)
                result.append(diagnostic)
        return tuple(result)

    def snapshot(self) -> SkillRunSnapshot:
        active = tuple(sorted(self._active.values(), key=lambda item: item.order))
        allowed: frozenset[str] | None = None
        if active:
            sets = [frozenset(item.definition.metadata.tools) for item in active]
            allowed = frozenset.intersection(*sets) if sets else frozenset()
        return SkillRunSnapshot(self._catalog, active, allowed)

    def _startup_errors(self, catalog: SkillCatalog) -> tuple[SkillDiagnostic, ...]:
        errors = [item for item in catalog.diagnostics if item.blocking]
        for definition in catalog.definitions:
            unknown = self._unknown_tool_names(definition)
            if unknown:
                errors.append(
                    SkillDiagnostic(
                        definition.entry_path,
                        f"Skill tools 包含未知普通工具：{', '.join(unknown)}。",
                        definition.source,
                        blocking=True,
                    )
                )
        return tuple(errors)

    def _filter_command_conflicts(self, catalog: SkillCatalog) -> SkillCatalog:
        definitions: list[SkillDefinition] = []
        diagnostics = list(catalog.diagnostics)
        for definition in catalog.definitions:
            command = f"/{definition.name}".lower()
            if command in self.reserved_commands:
                diagnostics.append(
                    SkillDiagnostic(
                        definition.entry_path,
                        f"Skill 名称 {definition.name!r} 与内置命令 {command} 冲突。",
                        definition.source,
                    )
                )
                continue
            definitions.append(definition)
        return SkillCatalog(tuple(definitions), tuple(diagnostics))

    def _unknown_tool_names(self, definition: SkillDefinition) -> tuple[str, ...]:
        return tuple(
            name for name in definition.metadata.tools if name not in self.known_tool_names
        )
