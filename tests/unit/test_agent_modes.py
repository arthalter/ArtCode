from __future__ import annotations

from artcode.agent import PLAN_MODE, READ_ONLY_TOOL_NAMES, ToolAccessPolicy


def openai_tool(name: str) -> dict:
    return {"type": "function", "function": {"name": name, "description": "", "parameters": {}}}


def test_full_policy_allows_every_tool() -> None:
    policy = ToolAccessPolicy()

    assert policy.allows("write_file") is True
    assert policy.filter_openai_tools([openai_tool("write_file")]) == [openai_tool("write_file")]


def test_plan_mode_allows_only_read_tools() -> None:
    tools = [openai_tool("read_file"), openai_tool("write_file"), openai_tool("search_text")]

    assert READ_ONLY_TOOL_NAMES == frozenset({"read_file", "find_files", "search_text"})
    assert [tool["function"]["name"] for tool in PLAN_MODE.tool_policy.filter_openai_tools(tools)] == [
        "read_file",
        "search_text",
    ]
