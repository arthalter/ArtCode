from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from artcode.persistence import (
    DurablePaths,
    SessionError,
    SessionJournal,
    SessionLockedError,
    SessionSelection,
    SessionService,
)
from artcode.workspace import ArtCodePaths, Workspace


pytestmark = pytest.mark.ch10_5
NOW = datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc)


def _paths(tmp_path: Path) -> DurablePaths:
    project = tmp_path / "project"
    project.mkdir()
    return DurablePaths.from_context(
        ArtCodePaths.create(tmp_path / "home"),
        Workspace.from_path(project),
    )


def test_session_service_uses_exact_shared_durable_paths(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    service = SessionService(paths)
    assert service.paths is paths
    assert service.catalog.sessions_dir == paths.sessions_dir


@pytest.mark.parametrize(
    "selection",
    [None, SessionSelection.latest(), SessionSelection.new()],
    ids=("implicit-default", "explicit-default", "new"),
)
def test_fresh_selection_creates_unrestored_context(
    tmp_path: Path,
    selection: SessionSelection | None,
) -> None:
    service = SessionService(_paths(tmp_path))
    context = service.start(selection, NOW)
    try:
        assert not context.status.restored
        assert context.status.recovered_messages == 0
        assert context.plan_memory.get() is None
        assert context.conversation.export_messages()[0]["role"] == "system"
    finally:
        service.close()


@pytest.mark.parametrize(
    ("selection", "message"),
    [
        (SessionSelection.resume("bad"), "格式非法"),
        (SessionSelection.resume("20260810-090000-dead"), "找不到"),
    ],
)
def test_explicit_resume_rejects_invalid_or_missing_session(
    tmp_path: Path,
    selection: SessionSelection,
    message: str,
) -> None:
    service = SessionService(_paths(tmp_path))
    with pytest.raises(SessionError, match=message):
        service.start(selection, NOW)
    service.close()


@pytest.mark.parametrize(
    "content",
    ["plain", "保留 用户 原文", "line1\nline2", "🙂汉字é", "  leading and trailing  "],
)
def test_resume_preserves_user_text_exactly(tmp_path: Path, content: str) -> None:
    paths = _paths(tmp_path)
    first = SessionService(paths)
    created = first.start(SessionSelection.new(), NOW)
    created.conversation.append_user(content)
    session_id = created.status.session_id
    first.close()

    resumed = SessionService(paths)
    context = resumed.start(SessionSelection.resume(session_id), NOW)
    try:
        users = [
            item["content"]
            for item in context.conversation.export_messages()
            if item["role"] == "user"
        ]
        assert users == [content]
        context.conversation.append_user("after-resume")
    finally:
        resumed.close()

    reopened = SessionService(paths)
    appended = reopened.start(SessionSelection.resume(session_id), NOW)
    try:
        users = [
            item["content"]
            for item in appended.conversation.export_messages()
            if item["role"] == "user"
        ]
        assert users == [content, "after-resume"]
    finally:
        reopened.close()


@pytest.mark.parametrize("selection_kind", ["default", "exact"])
def test_locked_session_default_falls_back_but_exact_resume_fails(
    tmp_path: Path,
    selection_kind: str,
) -> None:
    paths = _paths(tmp_path)
    active = SessionService(paths)
    active_context = active.start(SessionSelection.new(), NOW)
    contender = SessionService(paths)
    try:
        if selection_kind == "default":
            fallback = contender.start(SessionSelection.latest(), NOW)
            assert fallback.status.default_locked_new_session
            assert fallback.status.session_id != active_context.status.session_id
        else:
            with pytest.raises(SessionLockedError):
                contender.start(
                    SessionSelection.resume(active_context.status.session_id),
                    NOW,
                )
    finally:
        contender.close()
        active.close()


@pytest.mark.parametrize("state", ["before-start", "already-started", "after-close"])
def test_session_service_lifecycle_guards(tmp_path: Path, state: str) -> None:
    service = SessionService(_paths(tmp_path))
    if state == "before-start":
        with pytest.raises(SessionError, match="尚未启动"):
            _ = service.context
        service.close()
        return
    service.start(SessionSelection.new(), NOW)
    if state == "already-started":
        with pytest.raises(SessionError, match="重复启动"):
            service.start(SessionSelection.new(), NOW)
    else:
        service.close()
        with pytest.raises(SessionError, match="已经关闭"):
            service.start(SessionSelection.new(), NOW)
    service.close()


@pytest.mark.parametrize("limit", [0, 1, 2, 20])
def test_session_summary_honors_nonnegative_limit(tmp_path: Path, limit: int) -> None:
    paths = _paths(tmp_path)
    for index in range(3):
        service = SessionService(paths)
        context = service.start(
            SessionSelection.new(),
            NOW + timedelta(seconds=index),
        )
        context.conversation.append_user(f"title-{index}")
        service.close()
    reader = SessionService(paths)
    assert len(reader.sessions_summary(limit)) == min(limit, 3)
    reader.close()


@pytest.mark.parametrize("damage", ["complete-middle", "incomplete-tail"])
def test_recovery_reports_damage_without_rewriting_safe_users(
    tmp_path: Path,
    damage: str,
) -> None:
    paths = _paths(tmp_path)
    first = SessionService(paths)
    context = first.start(SessionSelection.new(), NOW)
    context.conversation.append_user("before")
    context.conversation.append_user("after")
    session_id = context.status.session_id
    journal_path = first.journal.path
    first.close()
    lines = journal_path.read_bytes().splitlines(keepends=True)
    if damage == "complete-middle":
        journal_path.write_bytes(lines[0] + b"bad-json\n" + lines[1])
    else:
        journal_path.write_bytes(b"".join(lines) + b'{"v":1')

    resumed = SessionService(paths)
    recovered = resumed.start(SessionSelection.resume(session_id), NOW)
    try:
        users = [
            item["content"]
            for item in recovered.conversation.export_messages()
            if item["role"] == "user"
        ]
        assert users == ["before", "after"]
        assert recovered.status.bad_line_count == (1 if damage == "complete-middle" else 0)
        assert recovered.status.truncated is (damage == "incomplete-tail")
    finally:
        resumed.close()


@pytest.mark.parametrize(
    ("mode", "assistant", "expected"),
    [
        ("plan", "plan A", "plan A"),
        ("normal", "normal answer", None),
        ("plan", "   ", None),
    ],
)
def test_plan_memory_only_recovers_nonempty_plan_assistant(
    tmp_path: Path,
    mode: str,
    assistant: str,
    expected: str | None,
) -> None:
    paths = _paths(tmp_path)
    first = SessionService(paths)
    context = first.start(SessionSelection.new(), NOW)
    context.conversation.append_user("request", mode=mode)
    context.conversation.append_assistant(assistant, mode=mode)
    session_id = context.status.session_id
    first.close()
    resumed = SessionService(paths)
    recovered = resumed.start(SessionSelection.resume(session_id), NOW)
    try:
        assert recovered.plan_memory.get() == expected
    finally:
        resumed.close()


@pytest.mark.parametrize(
    ("age_days", "deleted"),
    [(31, True), (30, False), (29, False)],
)
def test_cleanup_uses_strict_retention_boundary(
    tmp_path: Path,
    age_days: int,
    deleted: bool,
) -> None:
    paths = _paths(tmp_path)
    journal = SessionJournal.create(paths.sessions_dir, NOW - timedelta(days=age_days))
    path = journal.path
    journal.close()
    timestamp = (NOW - timedelta(days=age_days)).timestamp()
    os.utime(path, (timestamp, timestamp))
    service = SessionService(paths)
    report = service.cleanup_expired(NOW)
    assert (path.stem in report.deleted) is deleted
    assert path.exists() is (not deleted)
    service.close()


@pytest.mark.parametrize("mode", ["normal", "plan", "do"])
def test_journal_observer_preserves_supported_entry_mode(tmp_path: Path, mode: str) -> None:
    service = SessionService(_paths(tmp_path))
    context = service.start(SessionSelection.new(), NOW)
    context.conversation.append_user(f"mode={mode}", mode=mode)
    raw = json.loads(service.journal.path.read_text(encoding="utf-8"))
    assert raw["mode"] == mode
    assert raw["message"] == {"role": "user", "content": f"mode={mode}"}
    service.close()
