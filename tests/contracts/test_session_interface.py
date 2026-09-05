from __future__ import annotations

from pathlib import Path

import pytest

from artcode._session import LocalSession
from artcode.core.model import ProtocolMetadata, ToolRequest
from artcode.core.session import (
    AssistantCompletion,
    AssistantFact,
    SessionBusy,
    SessionSelection,
    ToolExchangeFact,
    UserFact,
)
from artcode.core.tool import ToolResult


def test_new_session_commits_append_only_facts_and_exactly_restores(tmp_path: Path) -> None:
    session = LocalSession(tmp_path, SessionSelection.new())
    session.commit_user("你好")
    session.commit_assistant("完成", AssistantCompletion.NATURAL)
    session_id = session.snapshot().session_id
    archive = session.archive_path
    session.close()

    restored = LocalSession(tmp_path, SessionSelection.exact(session_id))
    snapshot = restored.snapshot()

    assert snapshot.restored is True
    assert snapshot.facts == (UserFact("你好"), AssistantFact("完成", AssistantCompletion.NATURAL))
    assert archive.read_text(encoding="utf-8").count("\n") == 2
    restored.close()


def test_tool_exchange_is_one_complete_fact_with_opaque_metadata(tmp_path: Path) -> None:
    session = LocalSession(tmp_path, SessionSelection.new())
    requests = (
        ToolRequest("a", "read_file", '{"path":"a"}'),
        ToolRequest("b", "read_file", '{"path":"b"}'),
    )
    metadata = ProtocolMetadata(b'{"provider":"opaque-secret-shape"}')
    session.commit_tool_exchange(
        requests,
        (
            ToolResult("a", "read_file", True, "A"),
            ToolResult("b", "read_file", False, "B failed", "read_error"),
        ),
        metadata=metadata,
    )

    fact = session.snapshot().facts[0]
    assert isinstance(fact, ToolExchangeFact)
    assert fact.requests == requests
    assert fact.results[1].error_code == "read_error"
    assert fact.metadata == metadata
    assert "opaque-secret-shape" not in repr(fact.metadata)
    session.close()


def test_cancelled_exchange_fills_every_missing_result_before_commit(tmp_path: Path) -> None:
    session = LocalSession(tmp_path, SessionSelection.new())
    requests = (
        ToolRequest("a", "read_file", '{"path":"a"}'),
        ToolRequest("b", "read_file", '{"path":"b"}'),
    )

    session.commit_tool_exchange(
        requests,
        (ToolResult("a", "read_file", True, "A"),),
        cancelled=True,
    )

    fact = session.snapshot().facts[0]
    assert isinstance(fact, ToolExchangeFact)
    assert [item.call_id for item in fact.results] == ["a", "b"]
    assert fact.results[1].error_code == "cancelled"
    session.close()


def test_incomplete_or_mismatched_exchange_is_rejected_without_append(tmp_path: Path) -> None:
    session = LocalSession(tmp_path, SessionSelection.new())
    request = ToolRequest("a", "read_file", "{}")

    with pytest.raises(ValueError, match="完整"):
        session.commit_tool_exchange((request,), ())
    with pytest.raises(ValueError, match="匹配"):
        session.commit_tool_exchange(
            (request,), (ToolResult("wrong", "read_file", True, "x"),)
        )
    assert session.snapshot().facts == ()
    assert session.archive_path.read_bytes() == b""
    session.close()


def test_only_completed_assistant_text_can_be_committed(tmp_path: Path) -> None:
    session = LocalSession(tmp_path, SessionSelection.new())
    with pytest.raises(ValueError):
        session.commit_assistant("partial", "cancelled")  # type: ignore[arg-type]
    session.commit_assistant("length text", AssistantCompletion.LENGTH)
    assert session.snapshot().facts == (
        AssistantFact("length text", AssistantCompletion.LENGTH),
    )
    session.close()


def test_latest_selects_most_recent_writable_session_and_exact_lock_is_exclusive(tmp_path: Path) -> None:
    first = LocalSession(tmp_path, SessionSelection.new(), clock=lambda: 1.0)
    first_id = first.snapshot().session_id
    first.close()
    second = LocalSession(tmp_path, SessionSelection.new(), clock=lambda: 2.0)
    second_id = second.snapshot().session_id

    latest = LocalSession(tmp_path, SessionSelection.latest())
    assert latest.snapshot().session_id == first_id
    with pytest.raises(SessionBusy):
        LocalSession(tmp_path, SessionSelection.exact(second_id))
    latest.close()
    second.close()


def test_old_session_namespace_is_never_loaded(tmp_path: Path) -> None:
    old = tmp_path / ".artcode" / "sessions" / "old-session.jsonl"
    old.parent.mkdir(parents=True)
    old.write_text('{"role":"user","content":"legacy"}\n', encoding="utf-8")

    session = LocalSession(tmp_path, SessionSelection.latest())

    assert session.snapshot().restored is False
    assert session.snapshot().facts == ()
    assert session.archive_path != old
    session.close()
