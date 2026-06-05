from __future__ import annotations

from artcode.conversation import ConversationContext


def test_context_starts_with_system_prompt() -> None:
    context = ConversationContext()
    messages = context.export_messages()

    assert messages[0]["role"] == "system"
    assert "只支持纯对话" in messages[0]["content"]
    assert "不会执行工具" in messages[0]["content"]
    assert "不会读取文件" in messages[0]["content"]
    assert "不会编辑代码" in messages[0]["content"]


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
