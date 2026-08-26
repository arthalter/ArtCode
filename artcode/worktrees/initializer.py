from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import yaml


@dataclass(frozen=True)
class WorktreeInitRules:
    copy: tuple[str, ...]
    symlink: tuple[str, ...]
    hooks: str | None
    defaults: bool = False


def read_rules(path: Path) -> WorktreeInitRules:
    if not path.exists():
        return WorktreeInitRules(
            ("permissions.local.yml", ".artcode/instructions.md"),
            (".venv",),
            ".githooks",
            True,
        )
    if path.is_symlink():
        raise ValueError("worktree.yml 不能是符号链接。")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"无法读取 worktree.yml：{exc}") from exc
    if not isinstance(raw, dict) or set(raw) - {"version", "copy", "symlink", "hooks"}:
        raise ValueError("worktree.yml 只允许 version、copy、symlink、hooks。")
    if raw.get("version") != 1:
        raise ValueError("worktree.yml 的 version 必须为 1。")
    return WorktreeInitRules(
        _literal_paths(raw.get("copy", []), "copy"),
        _literal_paths(raw.get("symlink", []), "symlink"),
        _hook_path(raw.get("hooks", None)),
    )


def initialize_worktree(
    main_root: Path,
    worktree_root: Path,
    rules: WorktreeInitRules,
    *,
    is_ignored: Callable[[Path], bool],
    git_config: Callable[[str, str], None],
) -> None:
    for item in rules.copy:
        source, target = _pair(main_root, worktree_root, item)
        if not source.exists() and rules.defaults:
            continue
        if not source.exists():
            raise ValueError(f"Worktree 初始化项不存在：{item}")
        if (
            source.is_symlink()
            or _contains_symlink(source)
            or not is_ignored(source)
            or target.exists()
            or target.is_symlink()
        ):
            raise ValueError(f"不能复制 Worktree 初始化项：{item}")
        _copy_atomically(source, target)
    for item in rules.symlink:
        source, target = _pair(main_root, worktree_root, item)
        if not source.exists() and rules.defaults:
            continue
        if not source.exists():
            raise ValueError(f"Worktree 初始化项不存在：{item}")
        if not source.is_dir() or source.is_symlink() or not is_ignored(source) or target.exists() or target.is_symlink():
            raise ValueError(f"不能链接 Worktree 初始化项：{item}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to(source, target_is_directory=True)
    if rules.hooks is not None:
        _, hooks = _pair(worktree_root, worktree_root, rules.hooks)
        if not hooks.exists():
            if not rules.defaults:
                raise ValueError("worktree.yml 声明的 hooks 目录不存在。")
            return
        if hooks.is_symlink() or not hooks.is_dir():
            raise ValueError("hooks 必须是 Worktree 内的普通目录。")
        git_config("core.hooksPath", str(hooks))


def _literal_paths(raw: object, label: str) -> tuple[str, ...]:
    if not isinstance(raw, list) or any(not isinstance(item, str) for item in raw):
        raise ValueError(f"worktree.yml {label} 必须是字符串列表。")
    values = tuple(raw)
    if len(set(values)) != len(values):
        raise ValueError(f"worktree.yml {label} 不能重复。")
    for value in values:
        candidate = Path(value)
        if not value or candidate.is_absolute() or ".." in candidate.parts or any(char in value for char in "*?["):
            raise ValueError(f"worktree.yml {label} 只能包含项目内的相对字面路径。")
    return values


def _hook_path(raw: object) -> str | None:
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ValueError("worktree.yml hooks 必须是相对目录或 null。")
    return _literal_paths([raw], "hooks")[0]


def _pair(main_root: Path, worktree_root: Path, value: str) -> tuple[Path, Path]:
    main_root = main_root.resolve(strict=True)
    worktree_root = worktree_root.resolve(strict=True)
    source_literal = main_root / value
    target_literal = worktree_root / value
    _reject_symlink_parents(source_literal, main_root)
    _reject_symlink_parents(target_literal, worktree_root)
    source_resolved = source_literal.resolve(strict=False)
    target_resolved = target_literal.resolve(strict=False)
    if not _within(source_resolved, main_root) or not _within(target_resolved, worktree_root):
        raise ValueError("Worktree 初始化路径越界。")
    return source_literal, target_literal


def _copy_atomically(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".artcode-copy-", dir=target.parent))
    staged = temporary / target.name
    try:
        if source.is_dir():
            shutil.copytree(source, staged, symlinks=False)
        else:
            shutil.copy2(source, staged)
        os.replace(staged, target)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def _within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _reject_symlink_parents(path: Path, root: Path) -> None:
    """Reject lexical path components before resolving away symlink evidence."""

    relative = path.relative_to(root)
    cursor = root
    for part in relative.parts[:-1]:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ValueError(f"Worktree 初始化路径不能包含符号链接父目录：{cursor}")


def _contains_symlink(path: Path) -> bool:
    if path.is_symlink():
        return True
    if not path.is_dir():
        return False
    try:
        return any(candidate.is_symlink() for candidate in path.rglob("*"))
    except OSError:
        return True
