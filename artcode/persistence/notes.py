from __future__ import annotations

import os
import re
import secrets
import tempfile
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .models import (
    MemoryCategory,
    MemoryIndexReport,
    MemoryNote,
    MemoryOperation,
    MemoryScanReport,
    MemoryScope,
    MemoryStatus,
    MemoryUpdateReport,
)


MAX_NOTE_BYTES = 8 * 1024
MAX_SUMMARY_CHARS = 120
MAX_INDEX_LINES = 200
MAX_INDEX_BYTES = 25 * 1024
_FRONTMATTER_FIELDS = {
    "id",
    "scope",
    "category",
    "status",
    "title",
    "summary",
    "created_at",
    "updated_at",
    "source_session",
    "source_entry_ids",
}
_CATEGORY_ORDER = {
    MemoryCategory.PREFERENCE: 0,
    MemoryCategory.CORRECTION: 1,
    MemoryCategory.PROJECT_KNOWLEDGE: 2,
    MemoryCategory.REFERENCE: 3,
}
_CATEGORY_TITLES = {
    MemoryCategory.PREFERENCE: "用户偏好",
    MemoryCategory.CORRECTION: "纠正反馈",
    MemoryCategory.PROJECT_KNOWLEDGE: "项目知识",
    MemoryCategory.REFERENCE: "参考资料",
}
_MEMORY_ID_RE = re.compile(r"^mem-\d{8}-\d{6}-[0-9a-f]{4}$")
_SESSION_ID_RE = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{4}$")
_ENTRY_ID_RE = re.compile(r"^msg-\d{8}$")


class MemoryNoteError(ValueError):
    pass


class MemoryNoteStore:
    def __init__(self, root: Path, scope: MemoryScope) -> None:
        self.root = root
        self.scope = scope
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)

    @property
    def index_path(self) -> Path:
        return self.root / "index.md"

    def scan(self) -> MemoryScanReport:
        notes: list[MemoryNote] = []
        issues: list[str] = []
        for path in sorted(self.root.glob("mem-*.md"), key=lambda item: item.name):
            if path.is_symlink() or not path.is_file():
                issues.append(f"{path.name}: 不是可接受的普通笔记文件")
                continue
            try:
                note = parse_note(path)
                if note.scope is not self.scope:
                    raise MemoryNoteError("笔记作用域与目录不一致")
                notes.append(note)
            except (MemoryNoteError, OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
                issues.append(f"{path.name}: {exc}")
        return MemoryScanReport(tuple(notes), tuple(issues))

    def apply(
        self,
        operations: Sequence[MemoryOperation],
        now: datetime | None = None,
        *,
        source_session: str = "unknown",
    ) -> MemoryUpdateReport:
        current_time = _as_utc(now or datetime.now(timezone.utc))
        notes = {note.id: note for note in self.scan().notes}
        created = updated = superseded = rejected = 0
        for operation in operations:
            if operation.action == "noop":
                continue
            if operation.scope is not self.scope or (
                self.scope is MemoryScope.USER
                and operation.category is not MemoryCategory.PREFERENCE
            ):
                rejected += 1
                continue
            if operation.action == "create":
                if operation.target_id is not None:
                    rejected += 1
                    continue
                note_id = self._new_note_id(current_time)
                note = MemoryNote(
                    id=note_id,
                    scope=self.scope,
                    category=operation.category,
                    status=MemoryStatus.ACTIVE,
                    title=operation.title.strip(),
                    summary=operation.summary.strip(),
                    body=operation.body.strip(),
                    created_at=current_time,
                    updated_at=current_time,
                    source_session=source_session,
                    source_entry_ids=tuple(operation.source_entry_ids),
                )
                if not self._commit_valid(note):
                    rejected += 1
                    continue
                notes[note.id] = note
                created += 1
                continue
            target = notes.get(operation.target_id or "")
            if target is None or target.status is not MemoryStatus.ACTIVE:
                rejected += 1
                continue
            if operation.action == "update":
                note = replace(
                    target,
                    category=operation.category,
                    title=operation.title.strip(),
                    summary=operation.summary.strip(),
                    body=operation.body.strip(),
                    updated_at=current_time,
                    source_session=source_session,
                    source_entry_ids=tuple(operation.source_entry_ids),
                )
                if not self._commit_valid(note):
                    rejected += 1
                    continue
                notes[note.id] = note
                updated += 1
                continue
            if operation.action == "supersede":
                note = replace(
                    target,
                    status=MemoryStatus.SUPERSEDED,
                    updated_at=current_time,
                    source_session=source_session,
                    source_entry_ids=tuple(operation.source_entry_ids) or target.source_entry_ids,
                )
                if not self._commit_valid(note):
                    rejected += 1
                    continue
                notes[note.id] = note
                superseded += 1
                continue
            rejected += 1
        self.rebuild_index()
        status = "success" if rejected == 0 else ("partial" if created + updated + superseded else "rejected")
        return MemoryUpdateReport(status, created, updated, superseded, rejected)

    def rebuild_index(self) -> MemoryIndexReport:
        scan = self.scan()
        active = [note for note in scan.notes if note.status is MemoryStatus.ACTIVE]
        superseded_count = sum(note.status is MemoryStatus.SUPERSEDED for note in scan.notes)
        active.sort(key=lambda note: (_CATEGORY_ORDER[note.category], -note.updated_at.timestamp(), note.id))

        lines = [
            "# ArtCode 长期记忆索引",
            "",
            "> 自动生成的只读参考索引；真实来源是同目录中的 Markdown 笔记。",
            "",
        ]
        included = 0
        current_category: MemoryCategory | None = None
        for note in active:
            category_lines: list[str] = []
            if note.category is not current_category:
                category_lines = [f"## {_CATEGORY_TITLES[note.category]}", ""]
            line = f"- `{note.id}` [{note.title}]({note.id}.md) — {_trim_summary(note.summary)}"
            candidate = [*lines, *category_lines, line]
            if not _within_index_budget(candidate, reserve_lines=2):
                break
            lines = candidate
            current_category = note.category
            included += 1
        omitted = len(active) - included
        if omitted:
            footer = ["", f"> 未索引 {omitted} 条活跃笔记；文件仍保留在磁盘。"]
            while not _within_index_budget([*lines, *footer]) and len(lines) > 4:
                if lines[-1].startswith("- "):
                    included -= 1
                    omitted += 1
                lines.pop()
            lines.extend(footer)
        text = "\n".join(lines).rstrip() + "\n"
        _atomic_write(self.index_path, text.encode("utf-8"))
        return MemoryIndexReport(
            active_count=len(active),
            superseded_count=superseded_count,
            issue_count=len(scan.issues),
            omitted_count=omitted,
            byte_count=len(text.encode("utf-8")),
            line_count=len(text.splitlines()),
        )

    def read_index(self) -> str:
        try:
            return self.index_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            self.rebuild_index()
            return self.index_path.read_text(encoding="utf-8")

    def _new_note_id(self, now: datetime) -> str:
        prefix = now.astimezone().strftime("mem-%Y%m%d-%H%M%S")
        for _ in range(128):
            note_id = f"{prefix}-{secrets.token_hex(2)}"
            if not (self.root / f"{note_id}.md").exists():
                return note_id
        raise MemoryNoteError("无法生成不冲突的笔记 ID")

    def _commit_valid(self, note: MemoryNote) -> bool:
        if (
            not note.title
            or not note.summary
            or len(note.summary) > MAX_SUMMARY_CHARS
            or not note.body
            or not note.source_entry_ids
            or "\n" in note.title
            or "\r" in note.title
            or "\n" in note.summary
            or "\r" in note.summary
        ):
            return False
        try:
            rendered = render_note(note)
        except MemoryNoteError:
            return False
        encoded = rendered.encode("utf-8")
        if len(encoded) > MAX_NOTE_BYTES:
            return False
        _atomic_write(self.root / f"{note.id}.md", encoded)
        return True


def render_note(note: MemoryNote) -> str:
    if (
        not _MEMORY_ID_RE.fullmatch(note.id)
        or not isinstance(note.scope, MemoryScope)
        or not isinstance(note.category, MemoryCategory)
    ):
        raise MemoryNoteError("笔记字段非法")
    metadata = {
        "id": note.id,
        "scope": note.scope.value,
        "category": note.category.value,
        "status": note.status.value,
        "title": note.title,
        "summary": _trim_summary(note.summary),
        "created_at": _format_utc(note.created_at),
        "updated_at": _format_utc(note.updated_at),
        "source_session": note.source_session,
        "source_entry_ids": list(note.source_entry_ids),
    }
    frontmatter = yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False).strip()
    return f"---\n{frontmatter}\n---\n\n# {note.title}\n\n{note.body.strip()}\n"


def parse_note(path: Path) -> MemoryNote:
    raw = path.read_bytes()
    if len(raw) > MAX_NOTE_BYTES:
        raise MemoryNoteError("笔记超过 8KB")
    text = raw.decode("utf-8")
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        raise MemoryNoteError("缺少完整 frontmatter")
    frontmatter, body_part = text[4:].split("\n---\n", 1)
    metadata = yaml.safe_load(frontmatter)
    if not isinstance(metadata, dict) or set(metadata) != _FRONTMATTER_FIELDS:
        raise MemoryNoteError("frontmatter 字段集合不合法")
    note_id = _string(metadata["id"], "id")
    if not _MEMORY_ID_RE.fullmatch(note_id):
        raise MemoryNoteError("笔记 ID 格式非法")
    if path.name != f"{note_id}.md":
        raise MemoryNoteError("文件名与笔记 ID 不一致")
    title = _string(metadata["title"], "title")
    summary = _string(metadata["summary"], "summary")
    if any(character in title + summary for character in ("\n", "\r")):
        raise MemoryNoteError("标题和摘要必须保持单行")
    if len(summary) > MAX_SUMMARY_CHARS:
        raise MemoryNoteError("摘要超过 120 字符")
    source_ids = metadata["source_entry_ids"]
    if not isinstance(source_ids, list) or not source_ids or not all(isinstance(item, str) for item in source_ids):
        raise MemoryNoteError("source_entry_ids 必须是非空字符串列表")
    if not all(_ENTRY_ID_RE.fullmatch(item) for item in source_ids):
        raise MemoryNoteError("source_entry_ids 格式非法")
    heading = f"\n# {title}\n\n"
    if not body_part.startswith(heading):
        raise MemoryNoteError("正文标题与 frontmatter 不一致")
    body = body_part[len(heading) :].rstrip("\n")
    if not body:
        raise MemoryNoteError("笔记正文不能为空")
    try:
        scope = MemoryScope(_string(metadata["scope"], "scope"))
        category = MemoryCategory(_string(metadata["category"], "category"))
        status = MemoryStatus(_string(metadata["status"], "status"))
    except ValueError as exc:
        raise MemoryNoteError("作用域、类别或状态非法") from exc
    source_session = _string(metadata["source_session"], "source_session")
    if source_session != "unknown" and not _SESSION_ID_RE.fullmatch(source_session):
        raise MemoryNoteError("source_session 格式非法")
    return MemoryNote(
        id=note_id,
        scope=scope,
        category=category,
        status=status,
        title=title,
        summary=summary,
        body=body,
        created_at=_parse_utc(metadata["created_at"]),
        updated_at=_parse_utc(metadata["updated_at"]),
        source_session=source_session,
        source_entry_ids=tuple(source_ids),
    )


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _within_index_budget(lines: list[str], reserve_lines: int = 0) -> bool:
    if len(lines) + reserve_lines > MAX_INDEX_LINES:
        return False
    encoded = ("\n".join(lines) + "\n").encode("utf-8")
    return len(encoded) <= MAX_INDEX_BYTES


def _trim_summary(value: str) -> str:
    return value if len(value) <= MAX_SUMMARY_CHARS else value[: MAX_SUMMARY_CHARS - 1] + "…"


def _format_utc(value: datetime) -> str:
    return _as_utc(value).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_utc(value: Any) -> datetime:
    text = _string(value, "timestamp")
    if not text.endswith("Z"):
        raise MemoryNoteError("时间必须是 UTC Z 格式")
    try:
        return datetime.fromisoformat(text[:-1] + "+00:00").astimezone(timezone.utc)
    except ValueError as exc:
        raise MemoryNoteError("时间格式非法") from exc


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MemoryNoteError(f"{name} 必须是非空字符串")
    return value.strip()
