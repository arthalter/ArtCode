from __future__ import annotations

import json
from pathlib import Path
import sys

from artcode._tool import LocalTools
from artcode._workspace import LocalWorkspace
from artcode.core.tool import (
    ApprovalChoice,
    McpLoading,
    McpServerSource,
    McpServerState,
    PermissionMode,
    RunMode,
    ToolCall,
)


class ServerApprover:
    def __init__(self, allowed: bool) -> None:
        self.allowed = allowed
        self.requests: list[tuple[str, str]] = []

    async def approve_mcp_server(self, name: str, summary: str) -> bool:
        self.requests.append((name, summary))
        return self.allowed


class CallApprover:
    def __init__(self) -> None:
        self.requests = []

    async def approve(self, request):
        self.requests.append(request)
        return ApprovalChoice.ALLOW_ONCE


def fixture_server() -> Path:
    return Path(__file__).parents[1] / "integration" / "fixtures" / "mcp_test_server.py"


async def test_project_config_wholly_overrides_user_and_denial_prevents_process_start(tmp_path: Path) -> None:
    sentinel = tmp_path / "started"
    user = {
        "same": {"transport": "stdio", "command": sys.executable, "args": [str(fixture_server())]},
        "user-disabled": {"transport": "stdio", "enabled": False, "command": "missing"},
    }
    project = {
        "same": {
            "transport": "stdio",
            "command": sys.executable,
            "args": ["-c", f"from pathlib import Path; Path({str(sentinel)!r}).write_text('bad')"],
        }
    }
    approver = ServerApprover(False)
    tools = LocalTools()
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    workspace = LocalWorkspace(workspace_root)

    report = await tools.start_mcp(workspace, user, project, approver=approver)

    same = next(item for item in report.servers if item.name == "same")
    assert same.source is McpServerSource.PROJECT
    assert same.state is McpServerState.REJECTED
    assert approver.requests and approver.requests[0][0] == "same"
    assert not sentinel.exists()
    await tools.close()


async def test_plan_never_exposes_or_executes_active_mcp_tool(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    workspace = LocalWorkspace(root)
    tools = LocalTools(permission_mode=PermissionMode.FULL)
    await tools.start_mcp(
        workspace,
        {"live": {"transport": "stdio", "command": sys.executable, "args": [str(fixture_server())]}},
        {},
    )
    name = next(hit.name for hit in tools.search_mcp("echo") if "echo" in hit.name)
    run = tools.open_run(workspace, RunMode.PLAN)
    approver = CallApprover()

    result = await tools.execute_batch(
        run,
        (ToolCall("1", name, json.dumps({"text": "bad"})),),
        approver=approver,
    )

    assert name not in {item.name for item in run.descriptors}
    assert result[0].error_code == "tool_not_allowed"
    assert approver.requests == []
    await tools.close()


async def test_lazy_search_activation_persists_and_every_call_requires_approval(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    workspace = LocalWorkspace(root)
    tools = LocalTools(permission_mode=PermissionMode.FULL)
    report = await tools.start_mcp(
        workspace,
        {"live": {"transport": "stdio", "command": sys.executable, "args": [str(fixture_server())]}},
        {},
        loading=McpLoading.LAZY,
    )
    before = tools.open_run(workspace, RunMode.CHAT)
    hit = tools.search_mcp("Return the provided text")[0]

    assert report.discovered_tool_count >= 3
    assert report.active_tool_count == 0
    assert hit.active is False
    assert hit.name not in {item.name for item in before.descriptors}
    assert tools.activate_mcp(hit.name) is True
    after = tools.open_run(workspace, RunMode.CHAT)
    assert hit.name in {item.name for item in after.descriptors}

    no_approval = await tools.execute_batch(
        after, (ToolCall("1", hit.name, json.dumps({"text": "hello"})),)
    )
    approver = CallApprover()
    approved = await tools.execute_batch(
        after,
        (ToolCall("2", hit.name, json.dumps({"text": "hello"})),),
        approver=approver,
    )
    assert no_approval[0].error_code == "permission_required"
    assert approved[0].ok is True and "echo:hello" in approved[0].content
    assert len(approver.requests) == 1
    await tools.close()
