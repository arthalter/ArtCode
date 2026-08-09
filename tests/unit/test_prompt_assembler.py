from __future__ import annotations

from artcode.agent.modes import NORMAL_AGENT_MODE, PLAN_MODE
from artcode.prompting.assembler import PromptRequestAssembler
from artcode.tools import AllowedPathPolicy, ToolExecutionContext


def tool_context(tmp_path):
    return ToolExecutionContext(AllowedPathPolicy((tmp_path,)), default_cwd=tmp_path)


def openai_tool(name: str) -> dict:
    effect = "read" if name in {"read_file", "find_files", "search_text"} else "write"
    return {
        "type": "function",
        "x-artcode-origin": "builtin",
        "x-artcode-effect": effect,
        "function": {"name": name, "description": name, "parameters": {}},
    }


def test_assembler_appends_reminder_without_mutating_history(tmp_path) -> None:
    history = [{"role": "system", "content": "system"}, {"role": "user", "content": "hi"}]
    request = PromptRequestAssembler().assemble(
        history,
        NORMAL_AGENT_MODE,
        [openai_tool("read_file")],
        tool_context(tmp_path),
    )

    assert len(history) == 2
    assert request.messages[:-1] == tuple(history)
    assert request.messages[-1]["role"] == "user"
    assert "<system-reminder>" in request.messages[-1]["content"]


def test_assembler_filters_plan_mode_tools(tmp_path) -> None:
    request = PromptRequestAssembler().assemble(
        [{"role": "system", "content": "system"}],
        PLAN_MODE,
        [openai_tool("read_file"), openai_tool("write_file"), openai_tool("search_text")],
        tool_context(tmp_path),
    )

    assert [tool["function"]["name"] for tool in request.tools] == ["read_file", "search_text"]
    assert "write_file" in request.messages[-1]["content"]


def test_assembler_supports_no_tools_without_cache_control(tmp_path) -> None:
    request = PromptRequestAssembler().assemble(
        [{"role": "system", "content": "system"}],
        None,
        None,
        tool_context(tmp_path),
    )

    assert request.tools is None
    assert len(request.messages) == 1
    assert "cache_control" not in str(request.messages)
