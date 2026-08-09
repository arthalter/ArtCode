from __future__ import annotations

import pytest

from artcode.conversation import ConversationContext
from artcode.conversation.context import (
    ConversationPersistenceRejected,
    _tool_call_from_message,
    _tool_result_from_message,
)
from artcode.providers.tool_calls import ToolCall
from artcode.tools.results import error_result, success_result


def test_context_starts_with_system_prompt() -> None:
    context = ConversationContext()
    messages = context.export_messages()

    assert messages[0]["role"] == "system"
    assert "Agent Loop" in messages[0]["content"]
    assert "# 身份" in messages[0]["content"]
    assert "# 系统约束" in messages[0]["content"]
    assert "# 文本输出" in messages[0]["content"]
    assert "<system-reminder>" in messages[0]["content"]


def test_append_user_and_assistant_messages() -> None:
    context = ConversationContext()

    context.append_user("你好")
    context.append_assistant("你好，我是 ArtCode。")

    messages = context.export_messages()
    assert messages[-2] == {"role": "user", "content": "你好"}
    assert messages[-1] == {"role": "assistant", "content": "你好，我是 ArtCode。"}


def test_export_messages_returns_copy() -> None:
    context = ConversationContext()
    exported = context.export_messages()
    exported.append({"role": "user", "content": "mutated"})

    assert len(context.export_messages()) == 1


def test_snapshot_has_stable_ids_and_is_isolated() -> None:
    context = ConversationContext("system")
    context.append_user("原文\n`code`")
    snapshot = context.snapshot()
    exported_id = snapshot.entries[-1].id
    snapshot.entries[-1].payload["content"] = "changed"

    assert context.snapshot().entries[-1].id == exported_id
    assert context.export_messages()[-1]["content"] == "原文\n`code`"
    assert context.user_records([exported_id])[0].content == "原文\n`code`"


def test_replace_entries_is_transactional_by_version() -> None:
    context = ConversationContext("system")
    snapshot = context.snapshot()
    context.append_user("new")

    assert context.replace_entries_if_version(snapshot.version, snapshot.entries) is False
    assert context.export_messages()[-1]["content"] == "new"


def test_cancelled_reply_is_not_added_when_not_appended() -> None:
    context = ConversationContext()
    context.append_user("讲一段很长的话")

    messages = context.export_messages()

    assert messages[-1]["role"] == "user"
    assert all(message["role"] != "assistant" for message in messages[1:])


def test_append_assistant_tool_call_message() -> None:
    context = ConversationContext()
    call = ToolCall("call_1", "read_file", '{"path":"a.txt"}')

    context.append_assistant_tool_call([call])

    message = context.export_messages()[-1]
    assert message["role"] == "assistant"
    assert message["tool_calls"][0]["id"] == "call_1"
    assert message["tool_calls"][0]["function"]["name"] == "read_file"
    assert message["tool_calls"][0]["function"]["arguments"] == '{"path":"a.txt"}'


def test_append_tool_result_message() -> None:
    context = ConversationContext()
    call = ToolCall("call_1", "read_file", '{"path":"a.txt"}')
    result = success_result("read_file", "读取成功。", "hello")

    context.append_tool_result(call, result)

    message = context.export_messages()[-1]
    assert message["role"] == "tool"
    assert message["tool_call_id"] == "call_1"
    assert message["name"] == "read_file"
    assert "hello" in message["content"]


def test_multiple_tool_calls_can_each_receive_error_result() -> None:
    context = ConversationContext()
    calls = [
        ToolCall("call_1", "read_file", "{}"),
        ToolCall("call_2", "write_file", "{}"),
    ]

    context.append_assistant_tool_call(calls)
    for call in calls:
        context.append_tool_result(call, error_result(call.name, "too_many_tool_calls", "只允许一个工具。"))

    messages = context.export_messages()
    assert messages[-2]["tool_call_id"] == "call_1"
    assert messages[-1]["tool_call_id"] == "call_2"


def test_repair_incomplete_tool_calls_inserts_results_before_later_user_message() -> None:
    context = ConversationContext()
    calls = [
        ToolCall("call_1", "read_file", "{}"),
        ToolCall("call_2", "write_file", "{}"),
    ]
    context.append_assistant_tool_call(calls)
    context.append_tool_result(calls[0], success_result("read_file", "ok"))
    context.append_user("下一条消息")

    repaired = context.repair_incomplete_tool_calls()

    assert [call.id for call, _result in repaired] == ["call_2"]
    messages = context.export_messages()
    assistant_index = next(index for index, message in enumerate(messages) if message.get("tool_calls"))
    assert messages[assistant_index + 1]["tool_call_id"] == "call_1"
    assert messages[assistant_index + 2]["tool_call_id"] == "call_2"
    assert messages[assistant_index + 3] == {"role": "user", "content": "下一条消息"}


def test_repair_is_idempotent_for_complete_tool_turn() -> None:
    context = ConversationContext()
    call = ToolCall("call_1", "read_file", "{}")
    context.append_assistant_tool_call([call])
    context.append_tool_result(call, success_result("read_file", "ok"))

    assert context.repair_incomplete_tool_calls() == []
    assert context.repair_incomplete_tool_calls() == []


def test_version_and_observer_can_be_rebound() -> None:
    context = ConversationContext("system")
    assert context.version == 0

    class Observer:
        def on_entry(self, entry) -> None:
            raise RuntimeError("write failed")

    context.bind_observer(Observer())
    entry = context.append_user("saved in memory only")
    assert entry.persistence_failed
    assert isinstance(context.last_observer_error, RuntimeError)

    context.bind_observer(None)
    assert context.last_observer_error is None


def test_preflight_rejection_does_not_append_entry() -> None:
    class Observer:
        def validate_entry(self, entry) -> None:
            raise ValueError("too large")

        def on_entry(self, entry) -> None:
            raise AssertionError("must not run")

    context = ConversationContext("system", observer=Observer())
    with pytest.raises(ConversationPersistenceRejected, match="too large"):
        context.append_assistant("blocked")
    assert len(context.export_messages()) == 1


def test_missing_entry_updates_are_noops() -> None:
    context = ConversationContext("system")

    assert not context.replace_entry_content("missing", "new")
    assert not context.mark_persistence_failed("missing")


@pytest.mark.parametrize(
    "raw",
    [
        None,
        {},
        {"id": 1, "function": {}},
        {"id": "call", "function": []},
        {"id": "call", "function": {"name": 1, "arguments": "{}"}},
        {"id": "call", "function": {"name": "read", "arguments": {}}},
    ],
    ids=("none", "empty", "id", "function", "name", "arguments"),
)
def test_invalid_tool_call_messages_are_ignored(raw) -> None:
    assert _tool_call_from_message(raw) is None


@pytest.mark.parametrize(
    "content",
    [
        None,
        "not-json",
        "[]",
        "{}",
        '{"tool_name":"read","ok":true,"status":"success","message":"ok","content":"","error_code":null,"bytes_returned":{}}',
    ],
    ids=("none", "json", "array", "missing", "bad-bytes"),
)
def test_invalid_persisted_tool_results_are_ignored(content) -> None:
    assert _tool_result_from_message({"content": content}) is None
