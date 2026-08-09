from __future__ import annotations

import errno
import fcntl
import json
import os
import re
import secrets
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, BinaryIO, Iterator

from .models import CleanupReport, SessionDescriptor, SessionRecord, SessionRecoveryReport


SESSION_ID_RE = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{4}$")
ENTRY_ID_RE = re.compile(r"^msg-\d{8}$")
MAX_RECORD_BYTES = 4 * 1024 * 1024
TOOL_ARCHIVE_PREVIEW_BYTES = 2 * 1024
SESSION_RETENTION_DAYS = 30
SESSION_GAP_HOURS = 24
VALID_MODES = frozenset({"normal", "plan", "do"})


class SessionError(RuntimeError):
    pass


class SessionLockedError(SessionError):
    pass


class SessionPersistenceError(SessionError):
    pass


class SessionJournal:
    def __init__(self, path: Path, handle: BinaryIO) -> None:
        self.path = path
        self.session_id = path.stem
        self._handle = handle
        self._closed = False

    @classmethod
    def create(
        cls,
        sessions_dir: Path,
        now: datetime | None = None,
        *,
        max_attempts: int = 128,
    ) -> "SessionJournal":
        _private_directory(sessions_dir)
        local_now = now or datetime.now().astimezone()
        prefix = local_now.strftime("%Y%m%d-%H%M%S")
        for _ in range(max_attempts):
            session_id = f"{prefix}-{secrets.token_hex(2)}"
            path = sessions_dir / f"{session_id}.jsonl"
            try:
                fd = os.open(path, os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                continue
            handle = os.fdopen(fd, "a+b", buffering=0)
            try:
                _lock(handle, path)
            except Exception:
                handle.close()
                path.unlink(missing_ok=True)
                raise
            return cls(path, handle)
        raise SessionPersistenceError("无法生成不冲突的会话 ID。")

    @classmethod
    def open_existing(cls, path: Path) -> "SessionJournal":
        if not SESSION_ID_RE.fullmatch(path.stem) or path.suffix != ".jsonl":
            raise SessionError(f"非法会话文件名：{path.name}")
        if path.is_symlink() or not path.is_file():
            raise SessionError(f"会话文件不存在或不是普通文件：{path}")
        handle = path.open("r+b", buffering=0)
        try:
            _lock(handle, path)
            handle.seek(0, os.SEEK_END)
        except Exception:
            handle.close()
            raise
        return cls(path, handle)

    @property
    def closed(self) -> bool:
        return self._closed

    def append(self, entry: Any, mode: str = "normal") -> SessionRecord:
        if self._closed:
            raise SessionPersistenceError("会话日志已经关闭。")
        if mode not in VALID_MODES:
            mode = "normal"
        payload = dict(entry.payload)
        role = payload.get("role")
        if role == "system":
            raise SessionPersistenceError("System Prompt 不写入会话日志。")
        timestamp = datetime.now(timezone.utc)
        record = SessionRecord(1, timestamp, str(entry.id), mode, payload)
        encoded = _encode_record(record)
        if len(encoded) > MAX_RECORD_BYTES:
            if role != "tool":
                raise SessionPersistenceError("单条用户或助手消息超过 4MB，无法安全存档。")
            record = replace(record, message=_bounded_tool_message(payload, len(encoded)))
            encoded = _encode_record(record)
        try:
            written = self._handle.write(encoded)
            self._handle.flush()
        except OSError as exc:
            raise SessionPersistenceError(f"无法追加会话日志：{exc}") from exc
        if written != len(encoded):
            raise SessionPersistenceError("会话日志只写入了部分记录。")
        return record

    def validate_entry(self, entry: Any) -> None:
        mode = getattr(entry, "mode", "normal")
        if mode not in VALID_MODES:
            mode = "normal"
        payload = dict(entry.payload)
        if payload.get("role") == "system":
            raise SessionPersistenceError("System Prompt 不写入会话日志。")
        record = SessionRecord(
            1,
            datetime.now(timezone.utc),
            str(entry.id),
            mode,
            payload,
        )
        if len(_encode_record(record)) > MAX_RECORD_BYTES and payload.get("role") != "tool":
            raise SessionPersistenceError("单条用户或助手消息超过 4MB，无法安全存档。")

    def on_entry(self, entry: Any) -> None:
        self.append(entry, getattr(entry, "mode", "normal"))

    def truncate(self, offset: int) -> None:
        if self._closed:
            raise SessionPersistenceError("会话日志已经关闭。")
        self._handle.flush()
        os.ftruncate(self._handle.fileno(), offset)
        self._handle.seek(0, os.SEEK_END)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        finally:
            self._handle.close()

    def __enter__(self) -> "SessionJournal":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()


class SessionCatalog:
    def __init__(self, sessions_dir: Path) -> None:
        self.sessions_dir = sessions_dir

    def list_recent(self, limit: int = 20) -> tuple[SessionDescriptor, ...]:
        descriptors = [self._scan_path(path) for path in self._candidate_paths()]
        valid = [item for item in descriptors if item is not None]
        valid.sort(key=lambda item: (item.last_active_at, item.session_id), reverse=True)
        return tuple(valid[: max(limit, 0)])

    def latest_available(self) -> SessionDescriptor | None:
        recent = self.list_recent(limit=1)
        if not recent or recent[0].locked:
            return None
        return recent[0]

    def get(self, session_id: str) -> SessionDescriptor | None:
        if not SESSION_ID_RE.fullmatch(session_id):
            return None
        path = self.sessions_dir / f"{session_id}.jsonl"
        return self._scan_path(path) if path.exists() else None

    def cleanup_expired(self, now: datetime | None = None) -> CleanupReport:
        current = _as_utc(now or datetime.now(timezone.utc))
        cutoff = current - timedelta(days=SESSION_RETENTION_DAYS)
        deleted: list[str] = []
        locked: list[str] = []
        failed: list[str] = []
        for path in self._candidate_paths():
            descriptor = self._scan_path(path)
            if descriptor is None or descriptor.last_active_at >= cutoff:
                continue
            try:
                handle = path.open("r+b", buffering=0)
                try:
                    _lock(handle, path)
                except SessionLockedError:
                    handle.close()
                    locked.append(descriptor.session_id)
                    continue
                try:
                    path.unlink()
                    deleted.append(descriptor.session_id)
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                    handle.close()
            except OSError:
                failed.append(descriptor.session_id)
        return CleanupReport(tuple(deleted), tuple(locked), tuple(failed))

    def _candidate_paths(self) -> tuple[Path, ...]:
        if not self.sessions_dir.exists():
            return ()
        candidates = []
        for path in self.sessions_dir.iterdir():
            if path.is_symlink() or not path.is_file() or path.suffix != ".jsonl":
                continue
            if SESSION_ID_RE.fullmatch(path.stem):
                candidates.append(path)
        return tuple(sorted(candidates, key=lambda item: item.name))

    def _scan_path(self, path: Path) -> SessionDescriptor | None:
        if path.is_symlink() or not path.is_file() or not SESSION_ID_RE.fullmatch(path.stem):
            return None
        records, bad_count, _, _ = _scan_records(path)
        if records:
            last_active = records[-1][0].timestamp
        else:
            try:
                last_active = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            except OSError:
                return None
        return SessionDescriptor(
            session_id=path.stem,
            path=path,
            title=_session_title(item[0] for item in records),
            message_count=len(records),
            last_active_at=last_active,
            bad_line_count=bad_count,
            locked=_is_locked(path),
        )


class SessionRecovery:
    def recover(
        self,
        source: Path | SessionJournal,
        now: datetime | None = None,
    ) -> SessionRecoveryReport:
        owns_journal = isinstance(source, Path)
        journal = SessionJournal.open_existing(source) if owns_journal else source
        try:
            records_with_offsets, bad_count, tail_offset, issues = _scan_records(journal.path)
            truncated = False
            reason = ""
            if tail_offset is not None:
                journal.truncate(tail_offset)
                truncated = True
                reason = "incomplete_tail"

            safe_count, protocol_offset, protocol_reason = _safe_protocol_prefix(records_with_offsets)
            if protocol_offset is not None:
                journal.truncate(protocol_offset)
                records_with_offsets = records_with_offsets[:safe_count]
                truncated = True
                reason = protocol_reason

            records = tuple(item[0] for item in records_with_offsets)
            last_active = records[-1].timestamp if records else datetime.fromtimestamp(
                journal.path.stat().st_mtime, tz=timezone.utc
            )
            descriptor = SessionDescriptor(
                journal.session_id,
                journal.path,
                _session_title(records),
                len(records),
                last_active,
                bad_count,
                False,
            )
            current = _as_utc(now or datetime.now(timezone.utc))
            recovered_plan = None
            for record in records:
                message = record.message
                if (
                    record.mode == "plan"
                    and message.get("role") == "assistant"
                    and not message.get("tool_calls")
                    and isinstance(message.get("content"), str)
                    and message["content"].strip()
                ):
                    recovered_plan = message["content"].strip()
            return SessionRecoveryReport(
                descriptor,
                records,
                bad_count,
                truncated,
                reason,
                current - last_active > timedelta(hours=SESSION_GAP_HOURS),
                recovered_plan,
                tuple(issues),
            )
        finally:
            if owns_journal:
                journal.close()


def _encode_record(record: SessionRecord) -> bytes:
    raw = {
        "v": record.version,
        "timestamp": _format_utc(record.timestamp),
        "entry_id": record.entry_id,
        "mode": record.mode,
        "message": record.message,
    }
    return (json.dumps(raw, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def _parse_record(raw: bytes) -> SessionRecord | None:
    if len(raw) > MAX_RECORD_BYTES:
        return None
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict) or set(value) != {"v", "timestamp", "entry_id", "mode", "message"}:
        return None
    if value["v"] != 1 or not isinstance(value["entry_id"], str) or not ENTRY_ID_RE.fullmatch(value["entry_id"]):
        return None
    if value["mode"] not in VALID_MODES or not isinstance(value["message"], dict):
        return None
    try:
        timestamp = _parse_utc(value["timestamp"])
    except (TypeError, ValueError):
        return None
    if not _valid_message(value["message"]):
        return None
    return SessionRecord(1, timestamp, value["entry_id"], value["mode"], value["message"])


def _valid_message(message: dict[str, Any]) -> bool:
    role = message.get("role")
    if role not in {"user", "assistant", "tool"}:
        return False
    if not isinstance(message.get("content", ""), str):
        return False
    if "reasoning_content" in message and not isinstance(message["reasoning_content"], str):
        return False
    if role == "tool":
        return isinstance(message.get("tool_call_id"), str) and isinstance(message.get("name"), str)
    if role == "assistant" and "tool_calls" in message:
        calls = message["tool_calls"]
        if not isinstance(calls, list) or not calls:
            return False
        ids: set[str] = set()
        for call in calls:
            if not isinstance(call, dict) or not isinstance(call.get("id"), str) or call["id"] in ids:
                return False
            function = call.get("function")
            if call.get("type") != "function" or not isinstance(function, dict):
                return False
            if not isinstance(function.get("name"), str) or not isinstance(function.get("arguments"), str):
                return False
            ids.add(call["id"])
    return True


def _scan_records(
    path: Path,
) -> tuple[list[tuple[SessionRecord, int, int]], int, int | None, list[str]]:
    records: list[tuple[SessionRecord, int, int]] = []
    bad_count = 0
    tail_offset: int | None = None
    issues: list[str] = []
    try:
        with path.open("rb") as handle:
            for start, end, data, terminated, oversized in _bounded_lines(handle):
                if not terminated:
                    tail_offset = start
                    issues.append("会话末尾存在未完成记录，已安全移除。")
                    break
                if oversized:
                    bad_count += 1
                    issues.append("会话包含超过 4MB 的记录，已跳过。")
                    continue
                record = _parse_record(data)
                if record is None:
                    bad_count += 1
                    issues.append("会话包含无法解析的完整记录，已跳过。")
                    continue
                records.append((record, start, end))
    except OSError as exc:
        raise SessionError(f"无法扫描会话：{exc}") from exc
    return records, bad_count, tail_offset, issues


def _bounded_lines(handle: BinaryIO) -> Iterator[tuple[int, int, bytes, bool, bool]]:
    start = 0
    offset = 0
    buffer = bytearray()
    oversized = False
    while True:
        chunk = handle.read(64 * 1024)
        if not chunk:
            if offset > start:
                yield start, offset, bytes(buffer), False, oversized
            return
        for byte in chunk:
            offset += 1
            if not oversized:
                if len(buffer) < MAX_RECORD_BYTES + 1:
                    buffer.append(byte)
                else:
                    oversized = True
                    buffer.clear()
            if byte == 0x0A:
                data = bytes(buffer[:-1]) if not oversized else b""
                yield start, offset, data, True, oversized
                start = offset
                buffer.clear()
                oversized = False


def _safe_protocol_prefix(
    records: list[tuple[SessionRecord, int, int]],
) -> tuple[int, int | None, str]:
    index = 0
    while index < len(records):
        record, start, _ = records[index]
        message = record.message
        role = message.get("role")
        if role == "tool":
            return index, start, "orphan_tool_result"
        calls = message.get("tool_calls") if role == "assistant" else None
        if not isinstance(calls, list):
            index += 1
            continue
        expected = [call["id"] for call in calls]
        group = records[index + 1 : index + 1 + len(expected)]
        actual = [item[0].message.get("tool_call_id") for item in group if item[0].message.get("role") == "tool"]
        if len(group) != len(expected) or len(actual) != len(expected) or actual != expected:
            return index, start, "incomplete_tool_protocol"
        index += 1 + len(expected)
    return len(records), None, ""


def _session_title(records: Any) -> str:
    for item in records:
        record = item[0] if isinstance(item, tuple) else item
        message = record.message
        if message.get("role") != "user" or not isinstance(message.get("content"), str):
            continue
        normalized = " ".join(message["content"].split())
        if normalized:
            return normalized if len(normalized) <= 50 else normalized[:49] + "…"
    return "未命名会话"


def _bounded_tool_message(message: dict[str, Any], original_bytes: int) -> dict[str, Any]:
    content = str(message.get("content", ""))
    encoded = content.encode("utf-8")
    half = TOOL_ARCHIVE_PREVIEW_BYTES // 2
    head = encoded[:half].decode("utf-8", errors="ignore")
    tail = encoded[-half:].decode("utf-8", errors="ignore") if len(encoded) > half else ""
    placeholder = json.dumps(
        {
            "tool_name": message.get("name", "unknown"),
            "ok": False,
            "status": "archive_truncated",
            "message": "工具结果超过 4MB，完整内容未进入会话存档。",
            "content": f"{head}\n...[省略]...\n{tail}",
            "error_code": "session_record_too_large",
            "bytes_returned": original_bytes,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return {
        "role": "tool",
        "tool_call_id": message.get("tool_call_id", ""),
        "name": message.get("name", "unknown"),
        "content": placeholder,
    }


def _format_utc(value: datetime) -> str:
    return _as_utc(value).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_utc(value: Any) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("timestamp must be UTC")
    parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    return _as_utc(parsed)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _private_directory(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path, 0o700)


def _lock(handle: BinaryIO, path: Path) -> None:
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        if exc.errno in {errno.EACCES, errno.EAGAIN}:
            raise SessionLockedError(f"会话正在被其他 ArtCode 进程使用：{path.stem}") from exc
        raise


def _is_locked(path: Path) -> bool:
    try:
        handle = path.open("r+b", buffering=0)
    except OSError:
        return False
    try:
        try:
            _lock(handle, path)
        except SessionLockedError:
            return True
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        return False
    finally:
        handle.close()
