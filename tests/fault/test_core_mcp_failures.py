from __future__ import annotations

import json
from pathlib import Path
import sys

from artcode._tool import LocalTools
from artcode._workspace import LocalWorkspace
from artcode.core.tool import ApprovalChoice, PermissionMode, RunMode, ToolCall


class Allow:
    async def approve(self, request):
        return ApprovalChoice.ALLOW_ONCE


def fixture_server() -> Path:
    return Path(__file__).parents[1] / "integration" / "fixtures" / "mcp_test_server.py"


async def test_bad_server_does_not_break_builtin_or_healthy_server(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    workspace = LocalWorkspace(root)
    tools = LocalTools(permission_mode=PermissionMode.FULL)
    report = await tools.start_mcp(
        workspace,
        {
            "bad": {"transport": "stdio", "command": str(tmp_path / "missing")},
            "healthy": {"transport": "stdio", "command": sys.executable, "args": [str(fixture_server())]},
        },
        {},
    )
    run = tools.open_run(workspace, RunMode.CHAT)
    echo = next(item.name for item in run.descriptors if item.name.endswith("__echo"))

    results = await tools.execute_batch(
        run,
        (
            ToolCall("1", echo, json.dumps({"text": "still-ok"})),
            ToolCall("2", "find_files", json.dumps({"pattern": "*"})),
        ),
        approver=Allow(),
    )

    assert report.connected_count == 1
    assert any(item.name == "bad" and item.detail for item in report.servers)
    assert results[0].ok is True and "still-ok" in results[0].content
    assert results[1].ok is True
    await tools.close()


async def test_disconnected_server_failure_is_local_to_that_call(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    workspace = LocalWorkspace(root)
    server = {"transport": "stdio", "command": sys.executable, "args": [str(fixture_server())]}
    tools = LocalTools(permission_mode=PermissionMode.FULL)
    await tools.start_mcp(workspace, {"broken": server, "healthy": server}, {})
    run = tools.open_run(workspace, RunMode.CHAT)
    disconnect = next(item.name for item in run.descriptors if item.name.startswith("mcp__broken") and item.name.endswith("__disconnect"))
    echo = next(item.name for item in run.descriptors if item.name.startswith("mcp__healthy") and item.name.endswith("__echo"))

    results = await tools.execute_batch(
        run,
        (
            ToolCall("1", disconnect, "{}"),
            ToolCall("2", echo, json.dumps({"text": "alive"})),
        ),
        approver=Allow(),
    )

    assert results[0].error_code == "mcp_call_failed"
    assert results[1].ok is True and "alive" in results[1].content
    await tools.close()
