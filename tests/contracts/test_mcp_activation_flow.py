from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
import sys

import pytest

from artcode._tool import LocalTools
from artcode._workspace import LocalWorkspace
from artcode.core.tool import (
    ApprovalChoice, McpLoading, PermissionMode, RunMode, ShellPolicy,
    ToolCall, ToolEffect, ToolOrigin, ToolSource,
)


class Allow:
    async def approve(self, request):
        return ApprovalChoice.ALLOW_ONCE


async def start_lazy(tools: LocalTools, workspace: LocalWorkspace) -> None:
    fixture = Path(__file__).parents[1] / "integration" / "fixtures" / "mcp_test_server.py"
    await tools.start_mcp(
        workspace,
        {"local": {"transport": "stdio", "command": sys.executable, "args": [str(fixture)]}},
        {},
        loading=McpLoading.LAZY,
    )


async def test_model_can_search_then_call_lazy_mcp_only_after_request_refresh(tmp_path: Path) -> None:
    workspace = LocalWorkspace(tmp_path)
    tools = LocalTools()
    await start_lazy(tools, workspace)
    try:
        original = tools.open_run(workspace, RunMode.CHAT)
        names = {item.name for item in original.descriptors}
        assert "mcp_search_tools" in names
        assert "mcp__local__echo" not in names

        results = await tools.execute_batch(
            original,
            (
                ToolCall("search", "mcp_search_tools", '{"query":"provided text"}'),
                ToolCall("guess", "mcp__local__echo", '{"text":"same batch"}'),
            ),
            approver=Allow(),
        )
        assert results[0].ok
        payload = json.loads(results[0].content)
        assert payload["tools"][0]["name"] == "mcp__local__echo"
        assert payload["tools"][0]["active"] is True
        assert results[1].error_code == "tool_not_allowed"

        refreshed = tools.refresh_run(original)
        assert "mcp__local__echo" in {item.name for item in refreshed.descriptors}
        assert "mcp__local__echo" not in {item.name for item in original.descriptors}
        result = await tools.execute_batch(
            refreshed,
            (ToolCall("echo", "mcp__local__echo", '{"text":"next request"}'),),
            approver=Allow(),
        )
        assert result[0].ok and "echo:next request" in result[0].content
        later = tools.open_run(workspace, RunMode.CHAT)
        assert "mcp__local__echo" in {item.name for item in later.descriptors}
    finally:
        await tools.close()


async def test_search_filters_before_limit_and_refresh_preserves_frozen_run(tmp_path: Path) -> None:
    workspace = LocalWorkspace(tmp_path)
    tools = LocalTools()
    await start_lazy(tools, workspace)
    try:
        allowed = frozenset({"mcp_search_tools", "mcp__local__echo"})
        original = replace(
            tools.open_run(workspace, RunMode.CHAT, source=ToolSource.ISOLATED_SKILL, allowed_tools=allowed),
            execution_data=object(),
        )
        tools.set_permission_mode(PermissionMode.FULL)
        tools.set_shell_policy(ShellPolicy.EXPLICIT_UNSAFE)
        result = await tools.execute_batch(
            original,
            (ToolCall("search", "mcp_search_tools", '{"query":"local","limit":1}'),),
        )
        payload = json.loads(result[0].content)
        assert [item["name"] for item in payload["tools"]] == ["mcp__local__echo"]
        assert tools.search_mcp("local")[0].active is False  # alphabetically earlier, excluded hit

        # Another Run may activate more tools; a refresh must retain this Skill's ceiling.
        assert tools.activate_mcp("mcp__local__delayed")
        refreshed = tools.refresh_run(original)
        assert {item.name for item in refreshed.descriptors} == allowed
        assert replace(refreshed, descriptors=original.descriptors) == original
        assert refreshed.permission is original.permission
        assert refreshed.workspace is workspace
        assert refreshed.execution_data is original.execution_data
        assert tools.refresh_run(refreshed) is refreshed
    finally:
        await tools.close()


async def test_known_names_do_not_expand_plan_subagent_or_restricted_visibility(tmp_path: Path) -> None:
    workspace = LocalWorkspace(tmp_path)
    tools = LocalTools()
    await start_lazy(tools, workspace)
    try:
        assert {"mcp_search_tools", "mcp__local__echo"} <= tools.known_tool_names()
        helper = next(item for item in tools.open_run(workspace, RunMode.CHAT).descriptors if item.name == "mcp_search_tools")
        assert helper.effect is ToolEffect.CONTROL and helper.origin is ToolOrigin.SYSTEM
        assert not helper.subagent_allowed and not helper.rule_configurable
        runs = (
            tools.open_run(workspace, RunMode.PLAN),
            tools.open_run(workspace, RunMode.CHAT, source=ToolSource.SUBAGENT),
            tools.open_run(workspace, RunMode.CHAT, allowed_tools=frozenset({"read_file"})),
        )
        assert tools.activate_mcp("mcp__local__echo")
        for run in runs:
            refreshed = tools.refresh_run(run)
            assert refreshed is run
            results = await tools.execute_batch(refreshed, (
                ToolCall("search", "mcp_search_tools", '{"query":"echo"}'),
                ToolCall("guess", "mcp__local__echo", '{"text":"forbidden"}'),
            ))
            assert all(result.error_code == "tool_not_allowed" for result in results)

        other = LocalTools()
        try:
            with pytest.raises(ValueError, match="快照不属于"):
                other.refresh_run(runs[0])
        finally:
            await other.close()
    finally:
        await tools.close()


async def test_invalid_search_and_no_hits_are_local_without_activating_tools(tmp_path: Path) -> None:
    workspace = LocalWorkspace(tmp_path)
    tools = LocalTools()
    await start_lazy(tools, workspace)
    try:
        run = tools.open_run(workspace, RunMode.CHAT)
        invalid = (
            {}, {"query": "  "}, {"query": 12}, {"query": "echo", "limit": True},
            {"query": "echo", "limit": 0}, {"query": "echo", "limit": 51},
            {"query": "echo", "limit": "5"}, {"query": "echo", "extra": "field"},
        )
        for index, arguments in enumerate(invalid):
            result = await tools.execute_batch(run, (
                ToolCall(str(index), "mcp_search_tools", json.dumps(arguments)),
            ))
            assert result[0].error_code == "invalid_arguments"
        empty = await tools.execute_batch(run, (
            ToolCall("empty", "mcp_search_tools", '{"query":"no_such_capability"}'),
        ))
        assert empty[0].ok and json.loads(empty[0].content)["tools"] == []
        assert tools.refresh_run(run) is run
        assert not any(item.active for item in tools.search_mcp("local"))
    finally:
        await tools.close()


async def test_search_does_not_report_unavailable_server_as_activated(tmp_path: Path) -> None:
    workspace = LocalWorkspace(tmp_path)
    tools = LocalTools()
    await start_lazy(tools, workspace)
    try:
        run = tools.open_run(workspace, RunMode.CHAT)
        await tools.execute_batch(run, (
            ToolCall("discover", "mcp_search_tools", '{"query":"disconnect"}'),
        ))
        run = tools.refresh_run(run)
        failed = await tools.execute_batch(run, (
            ToolCall("disconnect", "mcp__local__disconnect", "{}"),
        ), approver=Allow())
        assert failed[0].error_code == "mcp_call_failed"
        result = await tools.execute_batch(run, (
            ToolCall("search", "mcp_search_tools", '{"query":"echo"}'),
        ))
        hit = json.loads(result[0].content)["tools"][0]
        assert hit["name"] == "mcp__local__echo"
        assert hit["active"] is False and hit["status"] == "server_unavailable"
        assert not tools.activate_mcp(hit["name"])
        assert "mcp__local__echo" not in {item.name for item in tools.refresh_run(run).descriptors}
    finally:
        await tools.close()


async def test_system_tool_dispatch_keeps_mcp_search_and_subagents_separate(tmp_path: Path) -> None:
    class Tasks:
        def list(self):
            return ()

    workspace = LocalWorkspace(tmp_path)
    tools = LocalTools()
    tools.register_subagents(Tasks())
    await start_lazy(tools, workspace)
    try:
        run = tools.open_run(workspace, RunMode.CHAT)
        results = await tools.execute_batch(run, (
            ToolCall("tasks", "task_list", "{}"),
            ToolCall("search", "mcp_search_tools", '{"query":"echo"}'),
        ))
        assert results[0].ok and json.loads(results[0].content) == []
        assert results[1].ok and json.loads(results[1].content)["tools"][0]["active"]
    finally:
        await tools.close()
