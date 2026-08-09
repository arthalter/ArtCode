from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from artcode.conversation import ConversationContext
from artcode.persistence import MAX_RECORD_BYTES, SessionJournal, SessionRecovery
from artcode.providers.tool_calls import ToolCall
from artcode.tools import success_result


pytestmark = [pytest.mark.ch10_5, pytest.mark.property]
SAFE_TEXT = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",)),
    min_size=1,
    max_size=120,
)


def _two_user_lines(tmp_path: Path, first: str, second: str) -> tuple[Path, list[bytes]]:
    journal = SessionJournal.create(tmp_path)
    conversation = ConversationContext(observer=journal)
    conversation.append_user(first)
    conversation.append_user(second)
    journal.close()
    return journal.path, journal.path.read_bytes().splitlines(keepends=True)


@settings(
    max_examples=20,
    deadline=None,
    suppress_health_check=(HealthCheck.function_scoped_fixture,),
)
@given(first=SAFE_TEXT, second=SAFE_TEXT, bad=st.binary(min_size=0, max_size=128).filter(lambda value: b"\n" not in value))
def test_complete_bad_record_preserves_safe_users_on_both_sides(
    tmp_path: Path,
    first: str,
    second: str,
    bad: bytes,
) -> None:
    path, lines = _two_user_lines(tmp_path, first, second)
    path.write_bytes(lines[0] + b"BAD" + bad + b"\n" + lines[1])

    report = SessionRecovery().recover(path)

    assert [record.message["content"] for record in report.records] == [first, second]
    assert report.bad_line_count == 1
    assert not report.truncated


@settings(
    max_examples=20,
    deadline=None,
    suppress_health_check=(HealthCheck.function_scoped_fixture,),
)
@given(tail=st.binary(min_size=1, max_size=256).filter(lambda value: b"\n" not in value))
def test_incomplete_tail_truncation_is_idempotent(tmp_path: Path, tail: bytes) -> None:
    path, lines = _two_user_lines(tmp_path, "before", "after")
    safe = b"".join(lines)
    path.write_bytes(safe + tail)

    first = SessionRecovery().recover(path)
    second = SessionRecovery().recover(path)

    assert first.truncated and first.truncated_reason == "incomplete_tail"
    assert not second.truncated
    assert path.read_bytes() == safe


@settings(
    max_examples=4,
    deadline=None,
    suppress_health_check=(HealthCheck.function_scoped_fixture,),
)
@given(extra=st.integers(min_value=1, max_value=32))
def test_oversized_complete_record_is_skipped_without_losing_neighbors(
    tmp_path: Path,
    extra: int,
) -> None:
    path, lines = _two_user_lines(tmp_path, "before-large", "after-large")
    path.write_bytes(lines[0] + b"x" * (MAX_RECORD_BYTES + extra) + b"\n" + lines[1])

    report = SessionRecovery().recover(path)

    assert [record.message["content"] for record in report.records] == [
        "before-large",
        "after-large",
    ]
    assert report.bad_line_count == 1
    assert any("超过 4MB" in issue for issue in report.issues)


@settings(
    max_examples=20,
    deadline=None,
    suppress_health_check=(HealthCheck.function_scoped_fixture,),
)
@given(call_count=st.integers(min_value=1, max_value=5), data=st.data())
def test_incomplete_tool_groups_always_recover_only_the_safe_prefix(
    tmp_path: Path,
    call_count: int,
    data: st.DataObject,
) -> None:
    result_count = data.draw(st.integers(min_value=0, max_value=call_count - 1))
    journal = SessionJournal.create(tmp_path)
    conversation = ConversationContext(observer=journal)
    conversation.append_user("safe-prefix")
    calls = [ToolCall(f"call-{index}", "read_file", "{}") for index in range(call_count)]
    conversation.append_assistant_tool_call(calls)
    for call in calls[:result_count]:
        conversation.append_tool_result(call, success_result("read_file", "ok"))
    journal.close()

    report = SessionRecovery().recover(journal.path)

    assert [record.message["role"] for record in report.records] == ["user"]
    assert report.truncated_reason == "incomplete_tool_protocol"
