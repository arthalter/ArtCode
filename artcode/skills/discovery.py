from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .models import (
    SkillCatalog,
    SkillDefinition,
    SkillDiagnostic,
    SkillMetadata,
    SkillMode,
    SkillSource,
)


_NAME = re.compile(r"^[a-z][a-z0-9-]*$")
_SOURCES = (SkillSource.PROJECT, SkillSource.USER, SkillSource.BUILTIN)


@dataclass(frozen=True)
class SkillRoots:
    project: Path
    user: Path
    builtin: Path

    def root_for(self, source: SkillSource) -> Path:
        return {
            SkillSource.PROJECT: self.project,
            SkillSource.USER: self.user,
            SkillSource.BUILTIN: self.builtin,
        }[source]


class SkillDiscovery:
    """Deterministically turns the three local Skill roots into a catalog."""

    def __init__(self, roots: SkillRoots) -> None:
        self.roots = roots

    def discover(self) -> SkillCatalog:
        candidates: list[SkillDefinition] = []
        diagnostics: list[SkillDiagnostic] = []
        for source in _SOURCES:
            root = self.roots.root_for(source)
            found, issues = self._discover_source(source, root)
            candidates.extend(found)
            diagnostics.extend(issues)

        grouped: dict[tuple[SkillSource, str], list[SkillDefinition]] = {}
        for candidate in candidates:
            grouped.setdefault((candidate.source, candidate.name), []).append(candidate)

        unique: list[SkillDefinition] = []
        for (source, name), items in sorted(
            grouped.items(), key=lambda item: (_source_rank(item[0][0]), item[0][1])
        ):
            if len(items) > 1:
                paths = "、".join(str(item.entry_path) for item in items)
                diagnostics.append(
                    SkillDiagnostic(
                        items[0].entry_path,
                        f"同一来源存在重复 Skill 名称 {name!r}：{paths}",
                        source,
                        blocking=True,
                    )
                )
                continue
            unique.append(items[0])

        selected: dict[str, SkillDefinition] = {}
        for candidate in sorted(
            unique,
            key=lambda item: (_source_rank(item.source), item.name, str(item.entry_path)),
        ):
            selected.setdefault(candidate.name, candidate)
        definitions = tuple(selected[name] for name in sorted(selected))
        return SkillCatalog(
            definitions,
            tuple(sorted(diagnostics, key=lambda item: (_source_rank(item.source), str(item.path), item.message))),
        )

    def _discover_source(
        self,
        source: SkillSource,
        root: Path,
    ) -> tuple[list[SkillDefinition], list[SkillDiagnostic]]:
        if not root.exists():
            return [], []
        if root.is_symlink() or not root.is_dir():
            return [], [SkillDiagnostic(root, "Skill 来源目录必须是普通目录。", source)]
        try:
            resolved_root = root.resolve(strict=True)
            entries = sorted(root.iterdir(), key=lambda path: path.name)
        except OSError as exc:
            return [], [SkillDiagnostic(root, f"无法读取 Skill 来源目录：{exc}", source)]

        definitions: list[SkillDefinition] = []
        diagnostics: list[SkillDiagnostic] = []
        for candidate in entries:
            if candidate.is_symlink():
                diagnostics.append(SkillDiagnostic(candidate, "Skill 入口不能是符号链接。", source))
                continue
            entry: Path | None = None
            package_root: Path | None = None
            if candidate.is_file() and candidate.suffix.lower() == ".md":
                entry, package_root = candidate, candidate
            elif candidate.is_dir():
                entry, package_root = candidate / "SKILL.md", candidate
                if entry.is_symlink():
                    diagnostics.append(SkillDiagnostic(entry, "Skill 入口不能是符号链接。", source))
                    continue
                if not entry.is_file():
                    continue
            if entry is None or package_root is None:
                continue
            try:
                definitions.append(
                    _parse_definition(source, resolved_root, entry, package_root)
                )
            except SkillParseError as exc:
                diagnostics.append(SkillDiagnostic(entry, str(exc), source))
        return definitions, diagnostics


class SkillParseError(ValueError):
    pass


def _parse_definition(
    source: SkillSource,
    source_root: Path,
    entry: Path,
    package_root: Path,
) -> SkillDefinition:
    try:
        resolved_entry = entry.resolve(strict=True)
        resolved_package = package_root.resolve(strict=True)
    except OSError as exc:
        raise SkillParseError(f"无法解析 Skill 入口：{exc}") from exc
    if not _inside(resolved_entry, source_root) or not _inside(resolved_package, source_root):
        raise SkillParseError("Skill 入口或能力包超出来源目录。")
    if entry.is_symlink() or package_root.is_symlink():
        raise SkillParseError("Skill 入口或能力包不能使用符号链接。")
    try:
        text = resolved_entry.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise SkillParseError("Skill 文件必须是 UTF-8 文本。") from exc
    except OSError as exc:
        raise SkillParseError(f"无法读取 Skill 文件：{exc}") from exc

    raw_metadata, sop = _split_frontmatter(text)
    metadata = _parse_metadata(raw_metadata)
    resources = _resources(resolved_package, source_root)
    fingerprint = _fingerprint(resources)
    return SkillDefinition(
        metadata=metadata,
        source=source,
        entry_path=resolved_entry,
        package_root=resolved_package,
        sop=sop,
        resources=resources,
        fingerprint=fingerprint,
    )


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n") and not text.startswith("---\r\n"):
        raise SkillParseError("Skill 文件必须以 YAML frontmatter 起始分隔符 --- 开头。")
    lines = text.splitlines(keepends=True)
    end = next((index for index, line in enumerate(lines[1:], 1) if line.strip() == "---"), None)
    if end is None:
        raise SkillParseError("Skill YAML frontmatter 缺少结束分隔符 ---。")
    raw_frontmatter = "".join(lines[1:end])
    try:
        loaded = yaml.safe_load(raw_frontmatter)
    except yaml.YAMLError as exc:
        raise SkillParseError(f"Skill YAML frontmatter 无法解析：{exc}") from exc
    if not isinstance(loaded, dict):
        raise SkillParseError("Skill YAML frontmatter 必须是对象。")
    return loaded, "".join(lines[end + 1:])


def _parse_metadata(raw: dict[str, Any]) -> SkillMetadata:
    allowed = {"name", "description", "tools", "mode", "history_turns", "model"}
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise SkillParseError(f"Skill frontmatter 包含未知字段：{', '.join(unknown)}。")
    name = raw.get("name")
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise SkillParseError("Skill name 必须是以小写字母开头、仅含小写字母数字和连字符的标识。")
    description = raw.get("description")
    if (
        not isinstance(description, str)
        or not description.strip()
        or "\n" in description
        or "\r" in description
    ):
        raise SkillParseError("Skill description 必须是一句非空文本。")
    tools = raw.get("tools")
    if not isinstance(tools, list) or any(
        not isinstance(item, str) or not item.strip() for item in tools
    ):
        raise SkillParseError("Skill tools 必须是字符串列表。")
    normalized_tools = tuple(item.strip() for item in tools)
    if len(set(normalized_tools)) != len(normalized_tools):
        raise SkillParseError("Skill tools 不能包含重复工具名。")
    mode_value = raw.get("mode", SkillMode.SHARED.value)
    try:
        mode = SkillMode(mode_value)
    except (TypeError, ValueError) as exc:
        raise SkillParseError("Skill mode 只能是 shared 或 isolated。") from exc
    history_turns = raw.get("history_turns", 0)
    if mode is SkillMode.SHARED:
        if "history_turns" in raw:
            raise SkillParseError("共享 Skill 不支持 history_turns。")
        history_turns = 0
    elif isinstance(history_turns, bool) or not isinstance(history_turns, int) or history_turns < 0:
        raise SkillParseError("独立 Skill 的 history_turns 必须是非负整数。")
    model = raw.get("model")
    if model is not None and (not isinstance(model, str) or not model.strip()):
        raise SkillParseError("Skill model 必须是非空文本。")
    return SkillMetadata(
        name=name,
        description=description.strip(),
        tools=normalized_tools,
        mode=mode,
        history_turns=history_turns,
        model=None if model is None else model.strip(),
    )


def _resources(package_root: Path, source_root: Path) -> tuple[Path, ...]:
    if package_root.is_file():
        return (package_root,)
    result: list[Path] = []
    try:
        entries: Iterable[Path] = package_root.rglob("*")
        for path in sorted(entries, key=lambda item: item.as_posix()):
            if path.is_symlink():
                raise SkillParseError(f"能力包资源不能是符号链接：{path}")
            if path.is_file():
                resolved = path.resolve(strict=True)
                if not _inside(resolved, source_root):
                    raise SkillParseError(f"能力包资源超出来源目录：{path}")
                result.append(resolved)
    except OSError as exc:
        raise SkillParseError(f"无法枚举 Skill 能力包资源：{exc}") from exc
    return tuple(result)


def _fingerprint(paths: tuple[Path, ...]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(str(path).encode("utf-8"))
        digest.update(b"\0")
        try:
            digest.update(path.read_bytes())
        except OSError as exc:
            raise SkillParseError(f"无法读取能力包资源：{path}（{exc}）") from exc
        digest.update(b"\0")
    return digest.hexdigest()


def _inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _source_rank(source: SkillSource) -> int:
    return _SOURCES.index(source)
