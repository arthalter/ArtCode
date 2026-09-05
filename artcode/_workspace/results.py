from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import uuid

from artcode.core.workspace import AtomicWriteFailure, StoredResult, TextSlice

from .files import slice_text


REFERENCE = re.compile(r"result:([0-9a-f]{32}):([0-9a-f]{32})\Z")


class ResultStore:
    def __init__(self, root: Path, scope_id: str, *, preview_bytes: int, read_char_limit: int) -> None:
        if preview_bytes < 1 or read_char_limit < 1:
            raise ValueError("结果预览和回读限制必须为正整数。")
        self.root = root / ".artcode" / "results" / scope_id
        self.scope_id = scope_id
        self.preview_bytes = preview_bytes
        self.read_char_limit = read_char_limit

    def store(self, source: str, content: str) -> StoredResult:
        self.root.mkdir(parents=True, exist_ok=True)
        identifier = uuid.uuid4().hex
        target = self.root / f"{identifier}.txt"
        temporary = self.root / f".{identifier}.tmp"
        data = content.encode("utf-8")
        fd = -1
        try:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            fd = os.open(temporary, flags, 0o600)
            with os.fdopen(fd, "wb") as handle:
                fd = -1
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
            directory_fd = os.open(self.root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError as exc:
            raise AtomicWriteFailure(f"大型结果原子写入失败：{source}（{exc}）") from exc
        finally:
            if fd >= 0:
                os.close(fd)
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
        preview = _preview(data, self.preview_bytes)
        return StoredResult(
            reference=f"result:{self.scope_id}:{identifier}",
            preview=preview,
            original_bytes=len(data),
            truncated=len(data) > self.preview_bytes * 2,
        )

    def read(self, reference: str, *, start_line: int | None, end_line: int | None) -> TextSlice:
        match = REFERENCE.fullmatch(reference)
        if match is None:
            raise ValueError("无效的结果引用。")
        scope_id, identifier = match.groups()
        if scope_id != self.scope_id:
            raise ValueError("结果引用不属于当前 Workspace scope。")
        if start_line is None or end_line is None:
            raise ValueError("大型结果回读必须提供完整行范围。")
        target = self.root / f"{identifier}.txt"
        try:
            content = target.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise ValueError("结果引用不存在或已经过期。") from exc
        return slice_text(
            content,
            start_line=start_line,
            end_line=end_line,
            char_limit=self.read_char_limit,
        )

    def close(self) -> None:
        if self.root.is_dir() and not self.root.is_symlink():
            shutil.rmtree(self.root)


def _preview(data: bytes, part_bytes: int) -> str:
    if len(data) <= part_bytes * 2:
        return data.decode("utf-8")
    head = data[:part_bytes].decode("utf-8", errors="ignore")
    tail = data[-part_bytes:].decode("utf-8", errors="ignore")
    return head + tail
