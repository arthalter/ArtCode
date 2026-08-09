from __future__ import annotations

from pathlib import Path

from artcode.agent import NORMAL_AGENT_MODE, ToolAccessPolicy
from artcode.permissions import (
    ApprovalChoice,
    PermissionEngine,
    PermissionState,
    RuleLoader,
    RulePaths,
    RuleWriter,
)
from artcode.permissions.service import PermissionService
from artcode.providers.tool_calls import ToolCall
from artcode.security import DangerousCommandValidator
from artcode.tools import ToolEnvironment, create_default_tool_registry
from artcode.tools.execution import ToolExecutionService
from artcode.workspace import Workspace


class FakeApprover:
    def __init__(self, choices: list[ApprovalChoice]) -> None:
        self.choices = choices
        self.requests = []

    async def request_approval(self, request):
        self.requests.append(request)
        return self.choices.pop(0)


async def test_default_hitl_persists_exact_local_rule_and_hot_reloads(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    workspace = Workspace.from_path(root)
    paths = RulePaths(tmp_path / "user.yml", tmp_path / "project.yml", workspace.local_permissions_file)
    rules = RuleLoader(paths)
    approver = FakeApprover([ApprovalChoice.ALLOW_ALWAYS])
    registry = create_default_tool_registry()
    state = PermissionState()
    executor = ToolExecutionService(
        registry,
        ToolEnvironment.from_workspace(workspace),
        PermissionService(
            state,
            engine=PermissionEngine(rules, DangerousCommandValidator.load()),
            approver=approver,
            rule_writer=RuleWriter(rules),
        ),
    )
    calls = [ToolCall("one", "write_file", '{"path":"note.txt","content":"one"}')]
    plan = executor.build_plan(calls, ToolAccessPolicy())
    events = [event async for event in executor.execute_plan(plan, mode=NORMAL_AGENT_MODE)]
    assert events[-1].payload["result"].ok
    assert (root / "note.txt").read_text(encoding="utf-8") == "one"
    assert "write_file(note.txt)" in workspace.local_permissions_file.read_text(encoding="utf-8")

    second_calls = [
        ToolCall(
            "two",
            "write_file",
            '{"path":"note.txt","content":"two","overwrite":true}',
        )
    ]
    second_plan = executor.build_plan(second_calls, ToolAccessPolicy())
    second_events = [event async for event in executor.execute_plan(second_plan, mode=NORMAL_AGENT_MODE)]
    assert second_events[-1].payload["result"].ok
    assert len(approver.requests) == 1
    assert (root / "note.txt").read_text(encoding="utf-8") == "two"
