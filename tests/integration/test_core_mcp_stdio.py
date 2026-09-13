from __future__ import annotations

import json
from pathlib import Path
import sys

from artcode._tool import LocalTools
from artcode._workspace import LocalWorkspace
from artcode.core.tool import ApprovalChoice, PermissionMode, RunMode, ToolCall, ToolEffect, ToolOrigin


class Allow:
    async def approve(self, request):
        return ApprovalChoice.ALLOW_ONCE


async def test_real_stdio_initializes_discovers_calls_and_closes(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    workspace = LocalWorkspace(root)
    fixture = Path(__file__).parent / "fixtures" / "mcp_test_server.py"
    tools = LocalTools(permission_mode=PermissionMode.FULL)
    report = await tools.start_mcp(
        workspace,
        {"stdio": {"transport": "stdio", "command": sys.executable, "args": [str(fixture), "--stderr-lines", "100"]}},
        {},
    )
    run = tools.open_run(workspace, RunMode.CHAT)
    descriptor = next(item for item in run.descriptors if item.name.endswith("__echo"))
    result = await tools.execute_batch(
        run,
        (ToolCall("1", descriptor.name, json.dumps({"text": "stdio"})),),
        approver=Allow(),
    )

    assert report.connected_count == 1
    assert descriptor.origin is ToolOrigin.MCP and descriptor.effect is ToolEffect.EXTERNAL
    assert result[0].ok is True and "echo:stdio" in result[0].content
    await tools.close()
