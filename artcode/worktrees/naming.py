from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from pathlib import Path


_SEGMENT = re.compile(r"^[a-z0-9][a-z0-9._-]{0,31}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


@dataclass(frozen=True)
class WorktreeName:
    value: str
    branch: str
    path: Path


def make_system_name() -> tuple[str, str]:
    suffix = secrets.token_hex(4)
    return f"agent-{suffix}", f"worktree-agent-{suffix}"


def validate_worktree_name(root: Path, name: str, *, system: bool = False) -> WorktreeName:
    if not isinstance(name, str) or not name:
        raise ValueError("Worktree 名称不能为空。")
    if len(name.encode("utf-8")) > 64:
        raise ValueError("Worktree 名称 UTF-8 长度不能超过 64 字节。")
    if name.startswith("~") or name.startswith("/") or "\\" in name or _CONTROL.search(name):
        raise ValueError("Worktree 名称包含不安全路径字符。")
    parts = name.split("/")
    if any(part in {"", ".", ".."} or not _SEGMENT.fullmatch(part) for part in parts):
        raise ValueError("Worktree 名称的每段必须是小写安全标识。")
    candidate = root.joinpath(*parts)
    try:
        root_resolved = root.resolve(strict=False)
        candidate_resolved = candidate.resolve(strict=False)
    except OSError as exc:
        raise ValueError("无法解析 Worktree 托管目录。") from exc
    if candidate_resolved == root_resolved or root_resolved not in candidate_resolved.parents:
        raise ValueError("Worktree 名称越过了托管目录边界。")
    branch = f"worktree-{name}"
    if system and not name.startswith("agent-"):
        raise ValueError("系统 Worktree 名称必须以 agent- 开头。")
    return WorktreeName(name, branch, candidate)
