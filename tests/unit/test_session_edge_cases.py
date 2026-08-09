from __future__ import annotations

import errno
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from artcode.persistence import (
    MAX_RECORD_BYTES,
    SessionCatalog,
    SessionError,
    SessionJournal,
    SessionLockedError,
    SessionPersistenceError,
    SessionRecovery,
)
from artcode.persistence.models import SessionRecord
from artcode.persistence.sessions import (
    _as_utc,
    _bounded_lines,
    _encode_record,
    _is_locked,
    _parse_record,
    _parse_utc,
    _safe_protocol_prefix,
    _session_title,
    _valid_message,
)


NOW = datetime(2026, 8, 10, 8, 0, tzinfo=timezone.utc)


def _entry(role: str = "user", content: str = "hello", **extra: object) -> SimpleNamespace:
    return SimpleNamespace(
        id="msg-00000001",
        mode="normal",
        payload={"role": role, "content": content, **extra},
    )


def _record(message: dict[str, object], entry_id: str = "msg-00000001") -> SessionRecord:
    return SessionRecord(1, NOW, entry_id, "normal", message)


def test_create_retries_collision_and_reports_exhaustion(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("artcode.persistence.sessions.secrets.token_hex", lambda _: "beef")
    first = SessionJournal.create(tmp_path, NOW)
    try:
        with pytest.raises(SessionPersistenceError, match="无法生成"):
            SessionJournal.create(tmp_path, NOW, max_attempts=2)
    finally:
        first.close()


def test_create_removes_file_if_locking_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_lock(handle: object, path: Path) -> None:
        raise OSError("lock failed")

    monkeypatch.setattr("artcode.persistence.sessions._lock", fail_lock)
    with pytest.raises(OSError, match="lock failed"):
        SessionJournal.create(tmp_path, NOW, max_attempts=1)
    assert not tuple(tmp_path.glob("*.jsonl"))


@pytest.mark.parametrize("name", ["bad.jsonl", "20260810-080000-abcd.txt"])
def test_open_existing_rejects_invalid_names(tmp_path: Path, name: str) -> None:
    path = tmp_path / name
    path.write_text("", encoding="utf-8")
    with pytest.raises(SessionError, match="非法会话文件名"):
        SessionJournal.open_existing(path)


def test_open_existing_rejects_missing_and_symlink(tmp_path: Path) -> None:
    missing = tmp_path / "20260810-080000-abcd.jsonl"
    with pytest.raises(SessionError, match="不存在"):
        SessionJournal.open_existing(missing)
    target = tmp_path / "target"
    target.write_text("", encoding="utf-8")
    missing.symlink_to(target)
    with pytest.raises(SessionError, match="不是普通文件"):
        SessionJournal.open_existing(missing)


def test_append_normalizes_mode_and_closed_journal_rejects_operations(tmp_path: Path) -> None:
    journal = SessionJournal.create(tmp_path, NOW)
    record = journal.append(_entry(), mode="invalid")
    assert record.mode == "normal"
    assert not journal.closed
    journal.close()
    assert journal.closed
    with pytest.raises(SessionPersistenceError, match="已经关闭"):
        journal.append(_entry())
    with pytest.raises(SessionPersistenceError, match="已经关闭"):
        journal.truncate(0)


def test_append_rejects_system_and_oversized_user(tmp_path: Path) -> None:
    with SessionJournal.create(tmp_path, NOW) as journal:
        with pytest.raises(SessionPersistenceError, match="System Prompt"):
            journal.append(_entry("system"))
        with pytest.raises(SessionPersistenceError, match="超过 4MB"):
            journal.append(_entry(content="x" * (MAX_RECORD_BYTES + 1)))


class _WriteHandle:
    def __init__(self, result: int | BaseException) -> None:
        self.result = result

    def write(self, data: bytes) -> int:
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result

    def flush(self) -> None:
        return None


@pytest.mark.parametrize(
    ("result", "message"),
    [(OSError("disk full"), "无法追加"), (0, "部分记录")],
)
def test_append_maps_write_failures(tmp_path: Path, result: int | BaseException, message: str) -> None:
    journal = SessionJournal(tmp_path / "20260810-080000-abcd.jsonl", _WriteHandle(result))  # type: ignore[arg-type]
    with pytest.raises(SessionPersistenceError, match=message):
        journal.append(_entry())


def test_validate_entry_and_observer_paths(tmp_path: Path) -> None:
    journal = SessionJournal.create(tmp_path, NOW)
    try:
        invalid_mode = _entry()
        invalid_mode.mode = "unknown"
        journal.validate_entry(invalid_mode)
        journal.on_entry(invalid_mode)
        with pytest.raises(SessionPersistenceError, match="System Prompt"):
            journal.validate_entry(_entry("system"))
        with pytest.raises(SessionPersistenceError, match="超过 4MB"):
            journal.validate_entry(_entry(content="x" * (MAX_RECORD_BYTES + 1)))
    finally:
        journal.close()


def test_catalog_empty_get_and_candidate_filtering(tmp_path: Path) -> None:
    catalog = SessionCatalog(tmp_path / "missing")
    assert catalog.list_recent() == ()
    assert catalog.latest_available() is None
    assert catalog.get("bad") is None

    directory = tmp_path / "sessions"
    directory.mkdir()
    (directory / "bad.jsonl").write_text("", encoding="utf-8")
    (directory / "20260810-080000-abcd.txt").write_text("", encoding="utf-8")
    subdir = directory / "20260810-080000-cafe.jsonl"
    subdir.mkdir()
    assert SessionCatalog(directory).list_recent() == ()


def test_catalog_gets_available_empty_session(tmp_path: Path) -> None:
    journal = SessionJournal.create(tmp_path, NOW)
    session_id = journal.session_id
    journal.close()
    catalog = SessionCatalog(tmp_path)
    assert catalog.get(session_id) is not None
    assert catalog.get("20260810-080000-ffff") is None
    assert catalog.latest_available().session_id == session_id  # type: ignore[union-attr]


def test_catalog_cleanup_reports_locked_and_unlink_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    journal = SessionJournal.create(tmp_path, NOW)
    path = journal.path
    old = datetime(2026, 6, 1, tzinfo=timezone.utc).timestamp()
    path.touch()
    import os

    os.utime(path, (old, old))
    locked = SessionCatalog(tmp_path).cleanup_expired(NOW)
    assert locked.locked == (journal.session_id,)
    journal.close()

    original_unlink = Path.unlink

    def fail_unlink(self: Path, *args: object, **kwargs: object) -> None:
        if self == path:
            raise OSError("read only")
        original_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_unlink)
    failed = SessionCatalog(tmp_path).cleanup_expired(NOW)
    assert failed.failed == (path.stem,)


@pytest.mark.parametrize(
    "raw",
    [
        b"x" * (MAX_RECORD_BYTES + 1),
        b"not json",
        b"[]",
        json.dumps({"v": 1}).encode(),
        json.dumps({"v": 2, "timestamp": "2026-08-10T08:00:00Z", "entry_id": "msg-00000001", "mode": "normal", "message": {"role": "user", "content": "x"}}).encode(),
        json.dumps({"v": 1, "timestamp": "bad", "entry_id": "msg-00000001", "mode": "normal", "message": {"role": "user", "content": "x"}}).encode(),
        json.dumps({"v": 1, "timestamp": "2026-08-10T08:00:00Z", "entry_id": "msg-00000001", "mode": "bad", "message": {"role": "user", "content": "x"}}).encode(),
    ],
)
def test_parse_record_rejects_malformed_records(raw: bytes) -> None:
    assert _parse_record(raw) is None


@pytest.mark.parametrize(
    "message",
    [
        {"role": "system", "content": "x"},
        {"role": "user", "content": 1},
        {"role": "assistant", "content": "", "reasoning_content": 1},
        {"role": "tool", "content": "x", "tool_call_id": 1, "name": "x"},
        {"role": "assistant", "content": "", "tool_calls": []},
        {"role": "assistant", "content": "", "tool_calls": [None]},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "c", "type": "bad", "function": {}}]},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "c", "type": "function", "function": {"name": 1, "arguments": "{}"}}]},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "c", "type": "function", "function": {"name": "x", "arguments": "{}"}}, {"id": "c", "type": "function", "function": {"name": "x", "arguments": "{}"}}]},
    ],
)
def test_valid_message_rejects_invalid_shapes(message: dict[str, object]) -> None:
    assert not _valid_message(message)


def test_recovery_of_empty_file_and_owned_journal_close(tmp_path: Path) -> None:
    journal = SessionJournal.create(tmp_path, NOW)
    path = journal.path
    journal.close()
    report = SessionRecovery().recover(path, now=NOW)
    assert report.records == ()
    assert report.descriptor.title == "未命名会话"


def test_bounded_lines_marks_oversized_and_unterminated(tmp_path: Path) -> None:
    path = tmp_path / "lines"
    path.write_bytes(b"x" * (MAX_RECORD_BYTES + 2) + b"\nlast")
    with path.open("rb") as handle:
        lines = list(_bounded_lines(handle))
    assert lines[0][3:] == (True, True)
    assert lines[1][2:] == (b"last", False, False)


def test_safe_protocol_accepts_complete_tool_group() -> None:
    assistant = _record({"role": "assistant", "content": "", "tool_calls": [{"id": "c", "type": "function", "function": {"name": "x", "arguments": "{}"}}]})
    tool = _record({"role": "tool", "content": "{}", "tool_call_id": "c", "name": "x"}, "msg-00000002")
    assert _safe_protocol_prefix([(assistant, 0, 1), (tool, 1, 2)]) == (2, None, "")


def test_timestamp_title_and_lock_helpers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError):
        _parse_utc(1)
    assert _as_utc(datetime(2026, 8, 10, 8)).tzinfo is timezone.utc
    assert _session_title([_record({"role": "assistant", "content": "x"})]) == "未命名会话"
    assert not _is_locked(tmp_path / "missing")

    path = tmp_path / "20260810-080000-abcd.jsonl"
    path.write_text("", encoding="utf-8")

    def fail_flock(*args: object) -> None:
        raise OSError(errno.EIO, "io")

    monkeypatch.setattr("artcode.persistence.sessions.fcntl.flock", fail_flock)
    with pytest.raises(OSError):
        SessionJournal.open_existing(path)
