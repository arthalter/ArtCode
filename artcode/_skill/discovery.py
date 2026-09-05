from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from artcode.core.skill import SkillDiagnostic, SkillSource, SkillSummary

from .parsing import SkillCandidate, parse_candidate


@dataclass(frozen=True, slots=True)
class Discovery:
    candidates: tuple[SkillCandidate, ...]
    summaries: tuple[SkillSummary, ...]
    diagnostics: tuple[SkillDiagnostic, ...]


def discover(
    project: Path,
    user: Path,
    builtin: Path,
    extensions: tuple[Path, ...],
) -> Discovery:
    sources = (
        (SkillSource.PROJECT, (project,)),
        (SkillSource.USER, (user,)),
        (SkillSource.BUILTIN, (builtin,)),
        (SkillSource.EXTENSION, extensions),
    )
    by_source: dict[SkillSource, dict[str, list[tuple[Path, Path]]]] = {}
    for source, roots in sources:
        grouped: dict[str, list[tuple[Path, Path]]] = {}
        for root in roots:
            if not root.exists():
                continue
            if root.is_symlink() or not root.is_dir():
                continue
            for item in sorted(root.iterdir(), key=lambda path: path.name):
                if item.is_file() and item.suffix.casefold() == ".md":
                    grouped.setdefault(item.stem, []).append((item, item))
                elif item.is_dir() and not item.is_symlink() and (item / "SKILL.md").exists():
                    grouped.setdefault(item.name, []).append((item / "SKILL.md", item))
                elif item.is_symlink():
                    logical = item.stem if item.suffix.casefold() == ".md" else item.name
                    grouped.setdefault(logical, []).append((item, item))
        by_source[source] = grouped

    all_names = sorted({name for grouped in by_source.values() for name in grouped})
    selected: list[SkillCandidate] = []
    diagnostics: list[SkillDiagnostic] = []
    for name in all_names:
        for source, _ in sources:
            entries = by_source[source].get(name, [])
            if not entries:
                continue
            if len(entries) != 1:
                diagnostics.append(SkillDiagnostic(name, source, "同一来源存在重复 Skill，已阻断回退。"))
                break
            entry, package = entries[0]
            try:
                selected.append(parse_candidate(entry, package, source, name))
            except (OSError, ValueError) as exc:
                diagnostics.append(SkillDiagnostic(name, source, f"高优先级 Skill 无效并阻断回退：{exc}"))
            break
    summaries = tuple(
        SkillSummary(item.metadata.name, item.metadata.description, item.source, item.metadata.mode)
        for item in sorted(selected, key=lambda item: item.metadata.name)
    )
    return Discovery(tuple(selected), summaries, tuple(diagnostics))
