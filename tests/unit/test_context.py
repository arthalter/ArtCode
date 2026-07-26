from __future__ import annotations

from artcode.conversation import ConversationContext
from artcode.providers.tool_calls import ToolCall
from artcode.tools.results import error_result, success_result


def test_context_starts_with_system_prompt() -> None:
    context = ConversationContext()
    messages = context.export_messages()

    assert messages[0]["role"] == "system"
    assert "ch05" in messages[0]["content"]
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
