from __future__ import annotations

from artcode.agent import PLAN_MODE, ToolAccessPolicy
from artcode.tools import ToolDescriptor, ToolEffect, ToolOrigin


def openai_tool(name: str, effect: ToolEffect = ToolEffect.WRITE) -> dict:
    return {
        "type": "function",
        "x-artcode-origin": "builtin",
        "x-artcode-effect": effect.value,
        "function": {"name": name, "description": "", "parameters": {}},
    }


def mcp_tool(name: str) -> dict:
    tool = openai_tool(name, ToolEffect.EXTERNAL)
    tool["x-artcode-origin"] = "mcp"
    return tool


def test_full_policy_allows_every_tool() -> None:
    policy = ToolAccessPolicy()

    descriptor = ToolDescriptor("write_file", "write", {}, ToolEffect.WRITE)
    assert policy.allows(descriptor) is True
    assert policy.filter_openai_tools([openai_tool("write_file")]) == [openai_tool("write_file")]


def test_plan_mode_allows_only_read_tools() -> None:
    tools = [
        openai_tool("read_file", ToolEffect.READ),
        openai_tool("write_file"),
        openai_tool("search_text", ToolEffect.READ),
    ]

    assert [tool["function"]["name"] for tool in PLAN_MODE.tool_policy.filter_openai_tools(tools)] == [
        "read_file",
        "search_text",
    ]


def test_plan_mode_allows_mcp_by_metadata_not_name_prefix() -> None:
    tools = [mcp_tool("external"), openai_tool("mcp__fake__write"), openai_tool("write_file")]
    selected = PLAN_MODE.tool_policy.filter_openai_tools(tools)
    assert [item["function"]["name"] for item in selected] == ["external"]
