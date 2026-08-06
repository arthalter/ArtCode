from __future__ import annotations

import json
import re
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from artcode.conversation import ConversationContext, ConversationPersistenceRejected
from artcode.persistence import (
    MAX_RECORD_BYTES,
    SessionCatalog,
    SessionJournal,
    SessionLockedError,
    SessionPersistenceError,
)
from artcode.providers.tool_calls import ToolCall
from artcode.tools import success_result


def test_journal_creates_single_private_jsonl_and_appends_records(tmp_path: Path) -> None:
    journal = SessionJournal.create(tmp_path, now=datetime(2026, 8, 6, 9, 8, 7))
    context = ConversationContext(observer=journal)
    try:
        context.append_user("你好", mode="normal")
        context.append_assistant("你好", mode="normal")
        assert re.fullmatch(r"20260806-090807-[0-9a-f]{4}", journal.session_id)
        assert stat.S_IMODE(journal.path.stat().st_mode) == 0o600
        assert list(tmp_path.iterdir()) == [journal.path]
        lines = journal.path.read_text(encoding="utf-8").splitlines()
        assert [json.loads(line)["message"]["role"] for line in lines] == ["user", "assistant"]
        assert all(json.loads(line)["v"] == 1 for line in lines)
    finally:
        journal.close()
        journal.close()


def test_journal_lock_prevents_concurrent_open(tmp_path: Path) -> None:
    journal = SessionJournal.create(tmp_path)
    try:
        with pytest.raises(SessionLockedError):
            SessionJournal.open_existing(journal.path)
    finally:
        path = journal.path
        journal.close()
    SessionJournal.open_existing(path).close()


def test_journal_rejects_oversized_text_and_bounds_oversized_tool_result(tmp_path: Path) -> None:
    journal = SessionJournal.create(tmp_path)
    context = ConversationContext(observer=journal)
    try:
        with pytest.raises(ConversationPersistenceRejected, match="4MB"):
            context.append_user("x" * (MAX_RECORD_BYTES + 1))
        call = ToolCall("call-1", "read_file", "{}")
        context.append_assistant_tool_call([call])
        context.append_tool_result(call, success_result("read_file", "ok", "x" * MAX_RECORD_BYTES))
        lines = journal.path.read_bytes().splitlines()
        assert all(len(line) <= MAX_RECORD_BYTES for line in lines)
        tool = json.loads(lines[-1])["message"]
        assert json.loads(tool["content"])["status"] == "archive_truncated"
    finally:
        journal.close()


def test_catalog_scans_title_sorting_limit_and_lock(tmp_path: Path) -> None:
    journals = []
    for index in range(3):
        journal = SessionJournal.create(tmp_path, now=datetime(2026, 8, 6, 9, 0, index))
        context = ConversationContext(observer=journal)
        context.append_user(("标题  \n" + "🙂" * 60) if index == 2 else f"title {index}")
        journals.append(journal)
        if index < 2:
            journal.close()
    try:
        recent = SessionCatalog(tmp_path).list_recent(limit=2)
        assert len(recent) == 2
        assert recent[0].locked
        assert len(recent[0].title) == 50
        assert recent[0].title.endswith("…")
        assert SessionCatalog(tmp_path).latest_available() is None
    finally:
        journals[-1].close()


def test_catalog_cleanup_uses_strict_thirty_day_boundary(tmp_path: Path) -> None:
    now = datetime(2026, 8, 6, tzinfo=timezone.utc)
    old = SessionJournal.create(tmp_path, now=datetime(2026, 7, 1))
    old_path = old.path
    old.close()
    exact = SessionJournal.create(tmp_path, now=datetime(2026, 7, 2))
    exact_path = exact.path
    exact.close()
    old_time = (now - timedelta(days=31)).timestamp()
    exact_time = (now - timedelta(days=30)).timestamp()
    old_path.touch()
    exact_path.touch()
    import os
    os.utime(old_path, (old_time, old_time))
    os.utime(exact_path, (exact_time, exact_time))

    report = SessionCatalog(tmp_path).cleanup_expired(now)

    assert old_path.stem in report.deleted
    assert not old_path.exists()
    assert exact_path.exists()
