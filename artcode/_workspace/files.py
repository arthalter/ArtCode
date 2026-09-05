from __future__ import annotations

import os
import secrets
import stat
from pathlib import Path

from artcode.core.workspace import AtomicWriteFailure, FileChange, TargetChanged, TextSlice

from .paths import PreparedTarget, open_parent


def read_utf8(root: Path, target: PreparedTarget) -> str:
    parent_fd = open_parent(target.access_root, target.resolved, create=False)
    file_fd = -1
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        file_fd = os.open(target.resolved.name, flags, dir_fd=parent_fd)
        metadata = os.fstat(file_fd)
        if (metadata.st_dev, metadata.st_ino) != target.identity:
            raise TargetChanged(f"读取前目标发生变化：{target.path}")
        with os.fdopen(file_fd, "r", encoding="utf-8") as handle:
            file_fd = -1
            return handle.read()
    finally:
        if file_fd >= 0:
            os.close(file_fd)
        os.close(parent_fd)


def atomic_write(root: Path, target: PreparedTarget, content: str, *, overwrite: bool) -> FileChange:
    parent_fd = open_parent(root, target.resolved, create=True)
    temp_name = f".{target.resolved.name}.artcode-{secrets.token_hex(8)}.tmp"
    temp_created = False
    try:
        exists = _entry_exists(parent_fd, target.resolved.name)
        identity = _entry_identity(parent_fd, target.resolved.name) if exists else None
        if identity != target.identity:
            raise TargetChanged(f"写入前目标发生变化：{target.path}")
        if exists and not overwrite:
            raise FileExistsError(f"文件已存在，且未声明覆盖：{target.path}")
        if exists and _entry_is_symlink(parent_fd, target.resolved.name):
            raise TargetChanged(f"写入前目标变成符号链接：{target.path}")

        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        temp_fd = os.open(temp_name, flags, 0o600, dir_fd=parent_fd)
        temp_created = True
        try:
            with os.fdopen(temp_fd, "w", encoding="utf-8") as handle:
                temp_fd = -1
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
        finally:
            if temp_fd >= 0:
                os.close(temp_fd)
        os.replace(temp_name, target.resolved.name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        temp_created = False
        os.fsync(parent_fd)
        return FileChange(target.path, created=not exists, bytes_written=len(content.encode("utf-8")))
    except (FileExistsError, TargetChanged):
        raise
    except OSError as exc:
        raise AtomicWriteFailure(f"原子写入失败：{target.path}（{exc}）") from exc
    finally:
        if temp_created:
            try:
                os.unlink(temp_name, dir_fd=parent_fd)
            except FileNotFoundError:
                pass
        os.close(parent_fd)


def slice_text(
    content: str,
    *,
    start_line: int | None,
    end_line: int | None,
    char_limit: int,
) -> TextSlice:
    if start_line is not None and (isinstance(start_line, bool) or start_line < 1):
        raise ValueError("start_line 必须大于等于 1。")
    if end_line is not None and (isinstance(end_line, bool) or end_line < 1):
        raise ValueError("end_line 必须大于等于 1。")
    start = start_line or 1
    lines = content.splitlines(keepends=True)
    total = len(lines)
    end = end_line if end_line is not None else total
    if end < start:
        raise ValueError("end_line 不能小于 start_line。")
    selected = "".join(lines[start - 1 : end]) if lines else ""
    truncated = len(selected) > char_limit
    text = selected[:char_limit]
    actual_end = min(end, total) if total else 0
    next_line = start if truncated else (actual_end + 1 if actual_end < total else None)
    return TextSlice(text, start, actual_end, total, truncated, next_line)


def _entry_exists(parent_fd: int, name: str) -> bool:
    try:
        os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return False
    return True


def _entry_identity(parent_fd: int, name: str) -> tuple[int, int]:
    metadata = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    return metadata.st_dev, metadata.st_ino


def _entry_is_symlink(parent_fd: int, name: str) -> bool:
    return stat.S_ISLNK(os.stat(name, dir_fd=parent_fd, follow_symlinks=False).st_mode)
