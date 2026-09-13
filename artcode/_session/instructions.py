from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


INCLUDE = re.compile(r"^\s*@include\s+(.+?)\s*$")


@dataclass(frozen=True, slots=True)
class InstructionDocument:
    source: str
    path: Path
    text: str


def load_instructions(
    workspace: Path,
    user_home: Path,
    *,
    budget_bytes: int = 64 * 1024,
    max_depth: int = 5,
) -> tuple[tuple[InstructionDocument, ...], tuple[str, ...]]:
    entries = (
        ("project-local", workspace / ".artcode" / "instructions.md", workspace / ".artcode"),
        ("project-root", workspace / "ARTCODE.md", workspace),
        ("user", user_home / "instructions.md", user_home),
    )
    documents: list[InstructionDocument] = []
    issues: list[str] = []
    remaining = budget_bytes
    for source, path, boundary in entries:
        if not path.exists():
            continue
        expanded = _expand(path, boundary, set(), 0, max_depth, issues)
        data = expanded.encode("utf-8")
        if len(data) > remaining:
            expanded = data[:remaining].decode("utf-8", errors="ignore")
            issues.append(f"{path}: 指令总预算已截断。")
        if expanded:
            documents.append(InstructionDocument(source, path, expanded))
            remaining -= len(expanded.encode("utf-8"))
        if remaining <= 0:
            break
    return tuple(documents), tuple(issues)


def _expand(
    path: Path,
    boundary: Path,
    visited: set[Path],
    depth: int,
    max_depth: int,
    issues: list[str],
) -> str:
    try:
        trusted = boundary.resolve(strict=True)
        resolved = path.resolve(strict=True)
    except OSError as exc:
        issues.append(f"{path}: 无法解析：{exc}")
        return ""
    if (resolved != trusted and trusted not in resolved.parents) or path.is_symlink() or not resolved.is_file():
        issues.append(f"{path}: 指令路径越界或不可信。")
        return ""
    if resolved in visited:
        issues.append(f"{path}: 指令 include 循环，已跳过。")
        return ""
    if depth > max_depth:
        issues.append(f"{path}: 指令 include 超过深度限制。")
        return ""
    visited.add(resolved)
    try:
        text = resolved.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        issues.append(f"{path}: 指令无法读取：{exc}")
        return ""
    output: list[str] = []
    fence: str | None = None
    for line in text.splitlines(keepends=True):
        stripped = line.lstrip()
        marker = "```" if stripped.startswith("```") else "~~~" if stripped.startswith("~~~") else None
        if marker:
            fence = None if fence == marker else marker if fence is None else fence
            output.append(line)
            continue
        match = None if fence else INCLUDE.match(line.rstrip("\r\n"))
        if not match:
            output.append(line)
            continue
        target = Path(match.group(1).strip())
        if target.is_absolute() or target.suffix.casefold() != ".md":
            issues.append(f"{path}: include 只允许相对 Markdown 路径。")
            continue
        candidate = resolved.parent / target
        try:
            candidate_resolved = candidate.resolve(strict=True)
        except OSError:
            issues.append(f"{path}: include 文件不存在。")
            continue
        if candidate_resolved != trusted and trusted not in candidate_resolved.parents:
            issues.append(f"{path}: include 路径越界，已跳过。")
            continue
        output.append(_expand(candidate, trusted, visited, depth + 1, max_depth, issues))
    return "".join(output)
