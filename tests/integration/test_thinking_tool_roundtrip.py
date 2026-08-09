from __future__ import annotations

from datetime import datetime, timezone

import pytest

from artcode.conversation import ConversationContext
from artcode.persistence.sessions import SessionJournal, SessionRecovery
from artcode.providers.tool_calls import ToolCall
from artcode.tools.results import success_result

pytestmark = pytest.mark.ch10_5


@pytest.mark.parametrize(
    "reasoning",
    [
        "reasoning",
        "中文推理",
        "line1\nline2",
        "quoted \"reason\"",
        "emoji 🧠",
        " leading and trailing ",
        "json {\"a\":1}",
        "tab\tvalue",
        "x" * 8_192,
        "mixed\n中文\tASCII",
    ],
    ids=("ascii", "unicode", "newline", "quote", "emoji", "spaces", "json", "tab", "long", "mixed"),
)
def test_reasoning_survives_conversation_jsonl_and_recovery(tmp_path, reasoning: str) -> None:
    journal = SessionJournal.create(tmp_path, datetime(2026, 8, 9, tzinfo=timezone.utc))
    context = ConversationContext("system", observer=journal)
    call = ToolCall("call-1", "read_file", '{"path":"a.txt"}')
    context.append_user("读取文件")
    context.append_assistant_tool_call((call,), reasoning_content=reasoning)
    context.append_tool_result(call, success_result("read_file", "ok", "content"))
    path = journal.path
    journal.close()

    report = SessionRecovery().recover(path)
    restored = ConversationContext.from_persisted_records(report.records)
    assistant = restored.export_messages()[2]
    assert assistant["reasoning_content"] == reasoning
    assert assistant["content"] == ""
    assert assistant["tool_calls"][0]["id"] == "call-1"
    assert restored.export_messages()[3]["tool_call_id"] == "call-1"
