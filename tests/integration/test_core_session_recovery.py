from __future__ import annotations

import json
from pathlib import Path

from artcode._session import LocalSession
from artcode.core.session import SessionSelection, UserFact


def test_recovery_stops_at_malformed_tool_exchange_safe_prefix(tmp_path: Path) -> None:
    session = LocalSession(tmp_path, SessionSelection.new())
    session.commit_user("safe prefix")
    identifier = session.snapshot().session_id
    archive = session.archive_path
    session.close()

    malformed_payload = {
        "kind": "tool_exchange",
        "requests": [{"id": "call", "name": "read_file", "arguments_json": "{}"}],
        "results": [],
        "metadata": None,
    }
    from artcode._session.storage import encode_record

    archive.write_bytes(
        archive.read_bytes()
        + encode_record(2, malformed_payload)
        + encode_record(3, {"kind": "user", "text": "unsafe suffix"})
    )

    restored = LocalSession(tmp_path, SessionSelection.exact(identifier))

    assert restored.snapshot().facts == (UserFact("safe prefix"),)
    assert any("Tool exchange" in issue for issue in restored.snapshot().recovery_issues)
    restored.close()


def test_snapshot_is_read_only_and_does_not_consume_or_rewrite_state(tmp_path: Path) -> None:
    session = LocalSession(tmp_path, SessionSelection.new())
    session.commit_user("fact")
    before = session.archive_path.read_bytes()

    first = session.snapshot()
    second = session.snapshot()

    assert first == second
    assert session.archive_path.read_bytes() == before
    session.close()
