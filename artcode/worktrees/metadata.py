from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .models import WorktreeLease


def write_metadata(lease: WorktreeLease) -> None:
    target = lease.metadata_path
    _reject_symlink_path(target.parent)
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"Worktree 元数据已存在：{target}")
    payload = {
        "task_id": lease.task_id,
        "name": lease.name,
        "path": str(lease.path),
        "branch": lease.branch,
        "baseline": lease.baseline,
        "main_workspace": str(lease.main_workspace),
        "created_at": lease.created_at,
        "initialization_paths": list(lease.initialization_paths),
    }
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=target.parent, delete=False) as handle:
            temporary = handle.name
            os.chmod(temporary, 0o600)
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        temporary = None
        os.chmod(target, 0o600)
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


def read_metadata(path: Path) -> dict[str, object] | None:
    try:
        if path.is_symlink() or not path.is_file():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    required = {
        "task_id", "name", "path", "branch", "baseline", "main_workspace",
        "created_at", "initialization_paths",
    }
    if not isinstance(raw, dict) or set(raw) != required:
        return None
    if not all(
        isinstance(raw[key], str)
        for key in required - {"created_at", "initialization_paths"}
    ):
        return None
    if not isinstance(raw["created_at"], (int, float)):
        return None
    if (
        not isinstance(raw["initialization_paths"], list)
        or any(not isinstance(item, str) for item in raw["initialization_paths"])
    ):
        return None
    return raw


def remove_metadata(path: Path) -> None:
    if path.is_symlink():
        raise ValueError("拒绝删除符号链接形式的 Worktree 元数据。")
    path.unlink(missing_ok=True)


def _reject_symlink_path(path: Path) -> None:
    cursor = path
    while cursor != cursor.parent:
        if cursor.is_symlink():
            raise ValueError(f"Worktree 元数据路径不能包含符号链接：{cursor}")
        cursor = cursor.parent
