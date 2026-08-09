from __future__ import annotations

import hashlib
import json

import pytest

from artcode.config import ContextConfig
from artcode.context_management import ContextArtifactStore, ContextManager, ContextSummarizer, LightweightCompactor
from artcode.context_management.models import CompressionTrigger
from artcode.context_management.retention import RetentionPlanner
from artcode.context_management.summarizer import SUMMARY_TITLES, VERBATIM_PLACEHOLDER
from artcode.conversation import ConversationContext
from artcode.providers.events import content_delta_event, done_event
from artcode.providers.tool_calls import ToolCall
from artcode.tools import success_result

pytestmark = [pytest.mark.ch10_5, pytest.mark.soak, pytest.mark.slow]


def valid_summary() -> str:
    sections = [
        f"## {index}. {title}\n{VERBATIM_PLACEHOLDER if index == 6 else 'summary'}"
        for index, title in enumerate(SUMMARY_TITLES, start=1)
    ]
    return "<analysis>draft</analysis><summary>" + "\n\n".join(sections) + "</summary>"


class Provider:
    async def stream(self, request):
        yield content_delta_event(valid_summary())
        yield done_event()


def user_payloads(context):
    return [
        (entry.id, entry.payload["content"])
        for entry in context.snapshot().entries
        if entry.payload.get("role") == "user"
    ]


def digest(values) -> str:
    return hashlib.sha256(json.dumps(values, ensure_ascii=False).encode()).hexdigest()


def assert_tool_protocol_closed(context) -> None:
    messages = context.export_messages()
    for index, message in enumerate(messages):
        calls = message.get("tool_calls")
        if not isinstance(calls, list):
            continue
        expected = [call["id"] for call in calls]
        actual = []
        cursor = index + 1
        while cursor < len(messages) and messages[cursor].get("role") == "tool":
            actual.append(messages[cursor]["tool_call_id"])
            cursor += 1
        assert actual == expected


@pytest.mark.parametrize(
    "scenario",
    ["plain", "tools", "unicode", "combined", "long-users"],
    ids=("plain", "tools", "unicode", "combined", "long-users"),
)
async def test_repeated_compaction_preserves_users_and_cleans_artifacts(tmp_path, scenario) -> None:
    context = ConversationContext("fixed")
    store = ContextArtifactStore(tmp_path, f"soak-{scenario}")
    store.start()
    manager = ContextManager(
        ContextConfig(),
        ContextSummarizer(Provider(), context),
        lightweight_compactor=LightweightCompactor(store),
        retention_planner=RetentionPlanner(20, 3),
    )
    expected = []
    try:
        for cycle in range(8):
            for index in range(5):
                content = f"user-{cycle}-{index}"
                if scenario == "unicode":
                    content = f"用户-{cycle}-{index}-🚀"
                elif scenario == "long-users":
                    content += "中" * 2_000
                entry = context.append_user(content)
                expected.append((entry.id, content))
                if scenario in {"tools", "combined"}:
                    call = ToolCall(f"call-{cycle}-{index}", "read_file", "{}")
                    context.append_assistant_tool_call((call,), reasoning_content="reasoning")
                    size = 30_000 if scenario == "combined" else 100
                    context.append_tool_result(call, success_result("read_file", "ok", "x" * size))
                context.append_assistant(f"answer-{cycle}-{index}-" + "a" * 100)
            if scenario == "combined":
                manager.run_lightweight(context)
            before_hash = digest(expected)
            report = await manager.compact(context, CompressionTrigger.MANUAL)
            assert report.status == "success"
            assert digest(user_payloads(context)) == before_hash
            assert user_payloads(context) == expected
            assert_tool_protocol_closed(context)
    finally:
        session_dir = store.session_dir
        store.close()
    assert not session_dir.exists()
