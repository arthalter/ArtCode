from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
from typing import Any

import yaml

from artcode.core.skill import SkillMode, SkillSource


NAME = re.compile(r"[a-z][a-z0-9-]{0,31}\Z")


@dataclass(frozen=True, slots=True)
class SkillMetadata:
    name: str
    description: str
    tools: tuple[str, ...]
    mode: SkillMode
    history_turns: int
    model: str | None


@dataclass(frozen=True, slots=True)
class SkillCandidate:
    metadata: SkillMetadata
    source: SkillSource
    entry: Path
    package_root: Path


@dataclass(frozen=True, slots=True)
class LoadedSkill:
    candidate: SkillCandidate
    sop: str
    fingerprint: str

    @property
    def name(self) -> str:
        return self.candidate.metadata.name


def parse_candidate(entry: Path, package_root: Path, source: SkillSource, logical_name: str) -> SkillCandidate:
    if entry.is_symlink() or package_root.is_symlink() or not entry.is_file():
        raise ValueError("Skill 入口必须是普通文件且不能是符号链接。")
    frontmatter, _ = _read_parts(entry, include_sop=False)
    metadata = _metadata(frontmatter)
    if metadata.name != logical_name:
        raise ValueError("Skill name 必须与文件或目录名一致。")
    return SkillCandidate(metadata, source, entry.resolve(strict=True), package_root.resolve(strict=True))


def load_skill(candidate: SkillCandidate) -> LoadedSkill:
    frontmatter, sop = _read_parts(candidate.entry, include_sop=True)
    metadata = _metadata(frontmatter)
    if metadata != candidate.metadata:
        candidate = SkillCandidate(metadata, candidate.source, candidate.entry, candidate.package_root)
    if not sop.strip():
        raise ValueError("Skill SOP 不能为空。")
    digest = hashlib.sha256()
    resources = (candidate.entry,) if candidate.package_root.is_file() else tuple(
        path for path in sorted(candidate.package_root.rglob("*")) if path.is_file()
    )
    for path in resources:
        if path.is_symlink():
            raise ValueError("Skill 能力包资源不能是符号链接。")
        resolved = path.resolve(strict=True)
        root = candidate.package_root if candidate.package_root.is_dir() else candidate.package_root.parent
        resolved_root = root.resolve(strict=True)
        if resolved != resolved_root and resolved_root not in resolved.parents:
            raise ValueError("Skill 能力包资源越界。")
        digest.update(str(resolved).encode())
        digest.update(path.read_bytes())
    return LoadedSkill(candidate, sop, digest.hexdigest())


def _read_parts(path: Path, *, include_sop: bool) -> tuple[dict[str, Any], str]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            first = handle.readline()
            if first.rstrip("\r\n") != "---":
                raise ValueError("Skill 必须以 YAML frontmatter 开头。")
            metadata_lines: list[str] = []
            for line in handle:
                if line.rstrip("\r\n") == "---":
                    break
                metadata_lines.append(line)
            else:
                raise ValueError("Skill frontmatter 缺少结束分隔符。")
            sop = handle.read() if include_sop else ""
    except UnicodeDecodeError as exc:
        raise ValueError("Skill 必须是 UTF-8 文本。") from exc
    try:
        raw = yaml.safe_load("".join(metadata_lines))
    except yaml.YAMLError as exc:
        raise ValueError(f"Skill frontmatter 无法解析：{exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError("Skill frontmatter 必须是对象。")
    return raw, sop


def _metadata(raw: dict[str, Any]) -> SkillMetadata:
    allowed = {"name", "description", "tools", "mode", "history_turns", "model"}
    unknown = set(raw) - allowed
    if unknown:
        raise ValueError(f"Skill frontmatter 包含未知字段：{', '.join(sorted(unknown))}")
    name = raw.get("name")
    if not isinstance(name, str) or NAME.fullmatch(name) is None:
        raise ValueError("Skill name 必须是小写安全标识。")
    description = raw.get("description")
    if not isinstance(description, str) or not description.strip() or "\n" in description or "\r" in description:
        raise ValueError("Skill description 必须是单行非空文本。")
    tools = raw.get("tools")
    if not isinstance(tools, list) or any(not isinstance(item, str) or not item for item in tools):
        raise ValueError("Skill tools 必须是工具名列表。")
    if len(set(tools)) != len(tools):
        raise ValueError("Skill tools 不能重复。")
    try:
        mode = SkillMode(raw.get("mode", "shared"))
    except (TypeError, ValueError) as exc:
        raise ValueError("Skill mode 只能是 shared 或 isolated。") from exc
    history = raw.get("history_turns", 0)
    if mode is SkillMode.SHARED and "history_turns" in raw:
        raise ValueError("shared Skill 不支持 history_turns。")
    if isinstance(history, bool) or not isinstance(history, int) or history < 0:
        raise ValueError("history_turns 必须是非负整数。")
    model = raw.get("model")
    if model is not None and (not isinstance(model, str) or not model.strip()):
        raise ValueError("Skill model 必须是非空字符串。")
    return SkillMetadata(name, description.strip(), tuple(tools), mode, history, model)
