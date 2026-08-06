from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from artcode.agent import PlanMemory
from artcode.conversation import ConversationContext
from artcode.persistence import SessionJournal, SessionRecovery
from artcode.providers.tool_calls import ToolCall
from artcode.tools import success_result


def _make_session(tmp_path: Path) -> tuple[Path, list[bytes]]:
    journal = SessionJournal.create(tmp_path, now=datetime(2026, 8, 6, 9, 0, 0))
    context = ConversationContext(observer=journal)
    context.append_user("first", mode="normal")
    context.append_assistant("plan body", mode="plan")
    journal.close()
    return journal.path, journal.path.read_bytes().splitlines(keepends=True)


def test_recovery_skips_complete_bad_line_and_removes_incomplete_tail(tmp_path: Path) -> None:
    path, lines = _make_session(tmp_path)
    path.write_bytes(lines[0] + b"not-json\n" + lines[1] + b'{"v":1')

    report = SessionRecovery().recover(path, now=datetime.now(timezone.utc))

    assert report.bad_line_count == 1
    assert report.truncated
    assert report.truncated_reason == "incomplete_tail"
    assert len(report.records) == 2
    assert report.recovered_plan == "plan body"
    assert path.read_bytes().endswith(lines[1])


def test_recovery_truncates_from_incomplete_tool_protocol(tmp_path: Path) -> None:
    journal = SessionJournal.create(tmp_path)
    context = ConversationContext(observer=journal)
    context.append_user("before")
    safe_size = journal.path.stat().st_size
    calls = [ToolCall("c1", "read_file", "{}"), ToolCall("c2", "search_text", "{}")]
    context.append_assistant_tool_call(calls)
    context.append_tool_result(calls[0], success_result("read_file", "ok"))
    journal.close()

    report = SessionRecovery().recover(journal.path)

    assert report.truncated_reason == "incomplete_tool_protocol"
    assert [record.message["role"] for record in report.records] == ["user"]
    assert journal.path.stat().st_size == safe_size


def test_recovery_truncates_orphan_tool_result(tmp_path: Path) -> None:
    path, lines = _make_session(tmp_path)
    raw = json.loads(lines[-1])
    raw["entry_id"] = "msg-00000003"
    raw["message"] = {"role": "tool", "tool_call_id": "missing", "name": "x", "content": "{}"}
    orphan = (json.dumps(raw) + "\n").encode()
    path.write_bytes(b"".join(lines) + orphan)

    report = SessionRecovery().recover(path)

    assert report.truncated_reason == "orphan_tool_result"
    assert len(report.records) == 2


def test_recovery_gap_is_strictly_more_than_twenty_four_hours(tmp_path: Path) -> None:
    path, _ = _make_session(tmp_path)
    report = SessionRecovery().recover(path)
    last = report.records[-1].timestamp

    exact = SessionRecovery().recover(path, now=last + timedelta(hours=24))
    over = SessionRecovery().recover(path, now=last + timedelta(hours=24, microseconds=1))

    assert not exact.gap_reminder_required
    assert over.gap_reminder_required


def test_conversation_restores_ids_archive_tool_result_and_plan(tmp_path: Path) -> None:
    journal = SessionJournal.create(tmp_path)
    source = ConversationContext(observer=journal)
    source.append_user("原文", mode="plan")
    call = ToolCall("c1", "read_file", "{}")
    source.append_assistant_tool_call([call], mode="plan")
    source.append_tool_result(call, success_result("read_file", "ok", "body"), mode="plan")
    source.append_assistant("最终计划", mode="plan")
    journal.close()
    report = SessionRecovery().recover(journal.path)

    restored = ConversationContext.from_persisted_records(report.records)
    new_entry = restored.append_user("next")
    plan = PlanMemory(report.recovered_plan)

    assert new_entry.id == "msg-00000006"
    assert restored.user_records(("msg-00000002",))[0].content == "原文"
    assert restored.snapshot().entries[3].raw_tool_result is not None
    assert plan.get() == "最终计划"
