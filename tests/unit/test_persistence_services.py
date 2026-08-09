from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from artcode.persistence import (
    DurablePaths,
    SessionError,
    SessionLockedError,
    SessionSelection,
    SessionService,
)
from artcode.workspace import ArtCodePaths, Workspace


def _paths(tmp_path: Path) -> DurablePaths:
    project = tmp_path / "project"
    project.mkdir()
    return DurablePaths.from_context(
        ArtCodePaths.create(tmp_path / "home"),
        Workspace.from_path(project),
    )


def test_new_then_default_resume_restores_conversation_and_plan(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    first = SessionService(paths)
    initial = first.start(SessionSelection.new())
    session_id = initial.status.session_id
    initial.conversation.append_user("制定计划", mode="plan")
    initial.conversation.append_assistant("计划 A", mode="plan")
    first.close()

    service = SessionService(paths)
    resumed = service.start(SessionSelection.latest())
    try:
        assert resumed.status.restored
        assert resumed.status.session_id == session_id
        assert resumed.status.recovered_messages == 2
        assert resumed.plan_memory.get() == "计划 A"
        assert resumed.conversation.append_user("继续").id == "msg-00000004"
    finally:
        service.close()


@pytest.mark.parametrize(
    ("session_id", "message"),
    [
        ("bad", "格式非法"),
        ("20260806-000000-dead", "找不到"),
    ],
    ids=("invalid", "missing"),
)
def test_exact_resume_rejects_invalid_or_missing_id(
    tmp_path: Path,
    session_id: str,
    message: str,
) -> None:
    service = SessionService(_paths(tmp_path))
    with pytest.raises(SessionError, match=message):
        service.start(SessionSelection.resume(session_id))
    service.close()


def test_locked_latest_falls_back_while_exact_resume_fails(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    active_service = SessionService(paths)
    active = active_service.start(SessionSelection.new())
    active.conversation.append_user("locked")

    fallback_service = SessionService(paths)
    fallback = fallback_service.start(SessionSelection.latest())
    exact_service = SessionService(paths)
    try:
        assert not fallback.status.restored
        assert fallback.status.default_locked_new_session
        assert fallback.status.session_id != active.status.session_id
        with pytest.raises(SessionLockedError):
            exact_service.start(SessionSelection.resume(active.status.session_id))
    finally:
        exact_service.close()
        fallback_service.close()
        active_service.close()


def test_long_gap_resume_requires_one_request_reminder(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    first = SessionService(paths)
    initial = first.start(SessionSelection.new())
    initial.conversation.append_user("old")
    session_id = initial.status.session_id
    journal = first.journal.path
    first.close()

    record = json.loads(journal.read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc)
    record["timestamp"] = (now - timedelta(hours=25)).isoformat().replace("+00:00", "Z")
    journal.write_text(json.dumps(record) + "\n", encoding="utf-8")

    service = SessionService(paths)
    resumed = service.start(SessionSelection.resume(session_id), now)
    try:
        assert resumed.resume_reminder_required
    finally:
        service.close()
