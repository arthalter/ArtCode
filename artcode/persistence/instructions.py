from __future__ import annotations

import re
from pathlib import Path

from .models import (
    InstructionBundle,
    InstructionDocument,
    InstructionIssue,
    InstructionScope,
)
from .paths import DurablePaths


INSTRUCTION_BUDGET_BYTES = 64 * 1024
MAX_INCLUDE_DEPTH = 5
_INCLUDE_RE = re.compile(r"^\s*@include\s+(.+?)\s*$")


class InstructionLoader:
    def __init__(self, paths: DurablePaths, *, budget_bytes: int = INSTRUCTION_BUDGET_BYTES) -> None:
        self.paths = paths
        self.budget_bytes = budget_bytes

    def load(self) -> InstructionBundle:
        documents: list[InstructionDocument] = []
        issues: list[InstructionIssue] = []
        remaining = self.budget_bytes
        entries = (
            (InstructionScope.PROJECT_LOCAL, self.paths.local_instruction, self.paths.project_instruction.parent),
            (InstructionScope.PROJECT_ROOT, self.paths.project_instruction, self.paths.project_instruction.parent),
            (InstructionScope.USER, self.paths.user_instruction, self.paths.user_instruction.parent),
        )
        for index, (scope, path, boundary) in enumerate(entries):
            if not path.exists():
                continue
            expanded, included = self._expand_entry(path, boundary, issues)
            if expanded is None:
                continue
            content, truncated = _fit_utf8_text(expanded, remaining)
            if content:
                byte_count = len(content.encode("utf-8"))
                documents.append(InstructionDocument(scope, path, content, byte_count, included))
                remaining -= byte_count
            if truncated:
                issues.append(
                    InstructionIssue(path, "budget_exceeded", "指令总量超过 64KB，当前或更低优先级内容已省略。")
                )
                for _, omitted, _ in entries[index + 1 :]:
                    if omitted.exists():
                        issues.append(
                            InstructionIssue(omitted, "budget_omitted", "低优先级指令因 64KB 总预算被省略。")
                        )
                break
        return InstructionBundle(tuple(documents), self.budget_bytes - remaining, tuple(issues))

    def _expand_entry(
        self,
        path: Path,
        boundary: Path,
        issues: list[InstructionIssue],
    ) -> tuple[str | None, tuple[Path, ...]]:
        try:
            trusted = boundary.resolve(strict=True)
            resolved = path.resolve(strict=True)
        except OSError as exc:
            issues.append(InstructionIssue(path, "unreadable", f"无法解析指令路径：{exc}"))
            return None, ()
        if not _within(resolved, trusted) or resolved.suffix.lower() != ".md" or not resolved.is_file():
            issues.append(InstructionIssue(path, "invalid_entry", "指令入口不是受信边界内的 Markdown 普通文件。"))
            return None, ()
        visited: set[Path] = set()
        included: list[Path] = []
        content = self._expand(resolved, trusted, 0, visited, included, issues)
        return content, tuple(included)

    def _expand(
        self,
        path: Path,
        boundary: Path,
        depth: int,
        visited: set[Path],
        included: list[Path],
        issues: list[InstructionIssue],
    ) -> str:
        if path in visited:
            issues.append(InstructionIssue(path, "include_cycle", "检测到重复或循环引用，已跳过。"))
            return ""
        visited.add(path)
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            issues.append(InstructionIssue(path, "invalid_utf8", "指令文件不是合法 UTF-8，已跳过。"))
            return ""
        except OSError as exc:
            issues.append(InstructionIssue(path, "unreadable", f"无法读取指令文件：{exc}"))
            return ""

        output: list[str] = []
        fence: str | None = None
        for line in text.splitlines(keepends=True):
            stripped = line.lstrip()
            marker = "```" if stripped.startswith("```") else "~~~" if stripped.startswith("~~~") else None
            if marker is not None:
                if fence is None:
                    fence = marker
                elif fence == marker:
                    fence = None
                output.append(line)
                continue
            match = None if fence is not None else _INCLUDE_RE.match(line.rstrip("\r\n"))
            if match is None:
                output.append(line)
                continue
            raw_target = match.group(1).strip()
            if depth >= MAX_INCLUDE_DEPTH:
                issues.append(InstructionIssue(path, "include_depth", "@include 已超过 5 层，已跳过。"))
                continue
            target = Path(raw_target)
            if target.is_absolute() or target.suffix.lower() != ".md":
                issues.append(InstructionIssue(path, "invalid_include", "@include 只接受相对 Markdown 路径。"))
                continue
            try:
                resolved = (path.parent / target).resolve(strict=True)
            except OSError as exc:
                issues.append(InstructionIssue(path, "include_missing", f"无法解析 @include：{exc}"))
                continue
            if not _within(resolved, boundary) or not resolved.is_file():
                issues.append(InstructionIssue(path, "include_outside", "@include 已越过受信边界或不是普通文件。"))
                continue
            included.append(resolved)
            output.append(self._expand(resolved, boundary, depth + 1, visited, included, issues))
        return "".join(output)


def _within(path: Path, boundary: Path) -> bool:
    return path == boundary or boundary in path.parents


def _fit_utf8_text(text: str, budget: int) -> tuple[str, bool]:
    encoded = text.encode("utf-8")
    if len(encoded) <= budget:
        return text, False
    if budget <= 0:
        return "", bool(text)
    prefix = encoded[:budget].decode("utf-8", errors="ignore")
    newline = prefix.rfind("\n")
    if newline >= 0:
        prefix = prefix[: newline + 1]
    else:
        prefix = ""
    return prefix, True
