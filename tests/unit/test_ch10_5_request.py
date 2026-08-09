from __future__ import annotations

from copy import deepcopy

import pytest

from artcode.agent import AgentRunRequest, NORMAL_AGENT_MODE, PLAN_MODE, RequestPreparer
from artcode.conversation import ConversationContext
from artcode.prompting.assembler import PromptRequestAssembler
from artcode.prompting.reminder import build_resume_reminder_message
from artcode.tools import AllowedPathPolicy, ToolExecutionContext, ToolRegistry

pytestmark = pytest.mark.ch10_5


def tool_context(tmp_path) -> ToolExecutionContext:
    return ToolExecutionContext(AllowedPathPolicy((tmp_path,)), default_cwd=tmp_path)


def schema(name: str) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": name,
            "parameters": {"type": "object", "properties": {}},
        },
        "x-artcode-origin": "builtin",
    }


@pytest.mark.parametrize(
    "maximum",
    [None, 1, 2, 3, 12, 13, 50, 100, 1_000, 1_000_000],
    ids=("none", "one", "two", "three", "old-limit", "past-old", "fifty", "hundred", "thousand", "million"),
)
def test_agent_run_request_accepts_unlimited_or_positive_limits(maximum) -> None:
    request = AgentRunRequest("hello", NORMAL_AGENT_MODE, max_iterations=maximum)
    assert request.max_iterations == maximum


@pytest.mark.parametrize(
    "maximum",
    [0, -1, -12, True, False, "1", "", 1.0, 0.0, [], {}, (), object(), complex(1), b"1"],
    ids=(
        "zero", "negative", "old-negative", "true", "false", "string", "empty-string",
        "float", "zero-float", "list", "dict", "tuple", "object", "complex", "bytes",
    ),
)
def test_agent_run_request_rejects_every_non_positive_integer_shape(maximum) -> None:
    with pytest.raises(ValueError, match="positive integer or None"):
        AgentRunRequest("hello", NORMAL_AGENT_MODE, max_iterations=maximum)


@pytest.mark.parametrize(
    ("mode", "include_resume", "durable"),
    [
        (NORMAL_AGENT_MODE, False, None),
        (NORMAL_AGENT_MODE, True, None),
        (NORMAL_AGENT_MODE, False, "DURABLE"),
        (NORMAL_AGENT_MODE, True, "DURABLE"),
        (PLAN_MODE, False, None),
        (PLAN_MODE, True, None),
        (PLAN_MODE, False, "DURABLE"),
        (PLAN_MODE, True, "DURABLE"),
        (None, False, None),
        (None, True, "DURABLE"),
    ],
    ids=(
        "normal", "normal-resume", "normal-durable", "normal-both",
        "plan", "plan-resume", "plan-durable", "plan-both",
        "no-mode", "no-mode-both",
    ),
)
def test_prompt_assembler_is_deterministic_and_does_not_mutate_inputs(
    tmp_path,
    mode,
    include_resume: bool,
    durable: str | None,
) -> None:
    messages = [{"role": "system", "content": "static"}, {"role": "user", "content": "hello"}]
    tools = [schema("read_file"), schema("write_file")]
    before_messages = deepcopy(messages)
    before_tools = deepcopy(tools)
    assembler = PromptRequestAssembler()

    first = assembler.assemble(
        messages,
        mode,
        tools,
        tool_context(tmp_path),
        durable_system_prompt=durable,
        include_resume_reminder=include_resume,
    )
    second = assembler.assemble(
        messages,
        mode,
        tools,
        tool_context(tmp_path),
        durable_system_prompt=durable,
        include_resume_reminder=include_resume,
    )

    assert first == second
    assert messages == before_messages
    assert tools == before_tools
    if first.tools:
        assert first.tools[0] is not tools[0]
        assert first.tools[0]["function"] is not tools[0]["function"]


@pytest.mark.parametrize(
    ("mode", "tools", "expected"),
    [
        (NORMAL_AGENT_MODE, [schema("read_file"), schema("write_file")], ("read_file", "write_file")),
        (PLAN_MODE, [schema("read_file"), schema("write_file")], ("read_file",)),
        (None, [schema("read_file"), schema("write_file")], ("read_file", "write_file")),
        (NORMAL_AGENT_MODE, [], ()),
        (NORMAL_AGENT_MODE, None, None),
    ],
    ids=("normal-all", "plan-read-only", "no-mode-all", "empty", "none"),
)
def test_prompt_assembler_filters_tools_without_leaking_internal_metadata(
    tmp_path,
    mode,
    tools,
    expected,
) -> None:
    request = PromptRequestAssembler().assemble([], mode, tools, tool_context(tmp_path))
    if expected is None:
        assert request.tools is None
        return
    assert tuple(item["function"]["name"] for item in request.tools or ()) == expected
    assert all("x-artcode-origin" not in item for item in request.tools or ())


@pytest.mark.parametrize(
    ("mode", "include_resume"),
    [
        (NORMAL_AGENT_MODE, True),
        (NORMAL_AGENT_MODE, False),
        (PLAN_MODE, True),
        (None, True),
        (None, False),
    ],
    ids=("normal-on", "normal-off", "plan-on", "no-mode-on", "no-mode-off"),
)
def test_resume_reminder_presence_is_entirely_explicit(tmp_path, mode, include_resume: bool) -> None:
    request = PromptRequestAssembler().assemble(
        [],
        mode,
        [],
        tool_context(tmp_path),
        include_resume_reminder=include_resume,
    )
    assert request.includes_resume_reminder is include_resume
    assert ("超过 24 小时" in str(request.messages)) is include_resume


@pytest.mark.parametrize("preview_count", [1, 2, 3, 5, 10], ids=("once", "twice", "three", "five", "ten"))
def test_request_previews_never_consume_pending_resume_reminder(tmp_path, preview_count: int) -> None:
    conversation = ConversationContext()
    conversation.append_user("continue")
    preparer = RequestPreparer(
        conversation,
        PromptRequestAssembler(),
        ToolRegistry(),
        tool_context(tmp_path),
        resume_reminder_required=True,
    )

    requests = [preparer.preview_request(NORMAL_AGENT_MODE) for _ in range(preview_count)]

    assert preparer.resume_reminder_pending
    assert all(request.includes_resume_reminder for request in requests)
    assert all("超过 24 小时" in str(request.messages) for request in requests)


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        ("role", "user"),
        ("open", "<system-reminder>"),
        ("gap", "超过 24 小时"),
        ("verify", "重新读取或验证"),
        ("close", "</system-reminder>"),
    ],
    ids=("role", "open-tag", "gap", "verify", "close-tag"),
)
def test_resume_reminder_message_has_stable_request_only_contract(field: str, expected: str) -> None:
    message = build_resume_reminder_message()
    value = message["role"] if field == "role" else message["content"]
    assert expected in value
