from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from artcode._session import LocalSession
from artcode.core.session import SessionCorrupt, SessionSelection, UserFact


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_partial_append_is_not_committed_and_next_restore_repairs_tail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = LocalSession(tmp_path, SessionSelection.new())
    session.commit_user("safe")
    identifier = session.snapshot().session_id
    real_write = os.write
    calls = 0

    def partial_then_fail(fd: int, data: bytes) -> int:
        nonlocal calls
        calls += 1
        if calls == 1:
            return real_write(fd, data[: max(1, len(data) // 2)])
        raise OSError("injected append failure")

    monkeypatch.setattr(os, "write", partial_then_fail)
    with pytest.raises(OSError):
        session.commit_user("not committed")
    assert session.snapshot().facts == (UserFact("safe"),)
    monkeypatch.setattr(os, "write", real_write)
    session.close()

    restored = LocalSession(tmp_path, SessionSelection.exact(identifier))
    assert restored.snapshot().facts == (UserFact("safe"),)
    assert restored.snapshot().recovery_issues
    assert restored.archive_path.read_bytes().endswith(b"\n")
    restored.close()


def test_bad_complete_record_is_isolated_without_modifying_archive(tmp_path: Path) -> None:
    session = LocalSession(tmp_path, SessionSelection.new())
    session.commit_user("one")
    session.commit_user("two")
    identifier = session.snapshot().session_id
    archive = session.archive_path
    session.close()
    lines = archive.read_bytes().splitlines(keepends=True)
    lines[0] = lines[0].replace(b'"one"', b'"bad"')
    archive.write_bytes(b"".join(lines))
    before = digest(archive)

    restored = LocalSession(tmp_path, SessionSelection.exact(identifier))

    assert restored.snapshot().facts == (UserFact("two"),)
    assert restored.snapshot().recovery_issues
    assert digest(archive) == before
    restored.close()


def test_failed_exact_restore_does_not_modify_unknown_directory(tmp_path: Path) -> None:
    target = tmp_path / ".artcode" / "ch14" / "sessions" / "session-invalid"
    target.mkdir(parents=True)
    marker = target / "marker"
    marker.write_text("keep", encoding="utf-8")
    before = digest(marker)

    with pytest.raises((ValueError, SessionCorrupt)):
        LocalSession(tmp_path, SessionSelection.exact("session-invalid"))
    assert digest(marker) == before
