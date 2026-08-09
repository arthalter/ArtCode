from __future__ import annotations

import json
from pathlib import Path

import pytest

from artcode.agent import AgentEventType, NORMAL_AGENT_MODE, ToolAccessPolicy
from artcode.permissions import PermissionState
from artcode.permissions.service import PermissionService
from artcode.providers.tool_calls import ToolCall
from artcode.tools import (
    ToolEnvironment,
    create_default_tool_registry,
)
from artcode.tools.execution import ToolExecutionService

pytestmark = pytest.mark.ch10_5


class MutatingPermissionService:
    def __init__(self, mutation) -> None:
        self.state = PermissionState()
        self.mutation = mutation
        self.called = False

    async def authorize(self, descriptor, prepared, context):
        if not self.called:
            self.called = True
            self.mutation()
        return None


def context_for(root: Path, *sensitive: Path) -> ToolEnvironment:
    return ToolEnvironment.from_workspace(
        root,
        sensitive_paths=tuple(sensitive),
    )


async def run_tool(
    root: Path,
    tool_name: str,
    arguments: dict,
    *,
    sensitive: tuple[Path, ...] = (),
    permission_service=None,
):
    service = ToolExecutionService(
        create_default_tool_registry(),
        context_for(root, *sensitive),
        permission_service or PermissionService(PermissionState()),
    )
    call = ToolCall("one", tool_name, json.dumps(arguments, ensure_ascii=False))
    plan = service.build_plan([call], ToolAccessPolicy())
    events = [event async for event in service.execute_plan(plan, mode=NORMAL_AGENT_MODE)]
    return next(
        event.payload["result"]
        for event in events
        if event.type is AgentEventType.TOOL_RESULT
    )


@pytest.mark.parametrize("depth", [1, 2, 4], ids=("one-level", "two-level", "four-level"))
async def test_write_tool_creates_missing_workspace_parents(tmp_path, depth) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    relative = "/".join([*(f"level_{index}" for index in range(depth)), "note.txt"])

    result = await run_tool(root, "write_file", {"path": relative, "content": "complete"})

    assert result.ok
    assert (root / relative).read_text(encoding="utf-8") == "complete"


@pytest.mark.parametrize("operation", ["read", "write", "edit"], ids=("read", "write", "edit"))
async def test_file_tools_follow_internal_symlink_to_real_target(tmp_path, operation) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    actual = root / "actual"
    actual.mkdir()
    note = actual / "note.txt"
    note.write_text("old", encoding="utf-8")
    (root / "link").symlink_to(actual, target_is_directory=True)
    if operation == "read":
        result = await run_tool(root, "read_file", {"path": "link/note.txt"})
        assert result.content == "old"
    elif operation == "write":
        result = await run_tool(root, "write_file", {"path": "link/new.txt", "content": "new"})
        assert (actual / "new.txt").read_text(encoding="utf-8") == "new"
    else:
        result = await run_tool(
            root,
            "edit_file",
            {"path": "link/note.txt", "old_text": "old", "new_text": "edited"},
        )
        assert note.read_text(encoding="utf-8") == "edited"
    assert result.ok


@pytest.mark.parametrize("operation", ["read", "write", "edit"], ids=("read", "write", "edit"))
async def test_file_tools_reject_symlink_to_outside_workspace(tmp_path, operation) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    note = outside / "note.txt"
    note.write_text("outside", encoding="utf-8")
    (root / "link").symlink_to(outside, target_is_directory=True)
    if operation == "read":
        name, arguments = "read_file", {"path": "link/note.txt"}
    elif operation == "write":
        name, arguments = "write_file", {"path": "link/new.txt", "content": "new"}
    else:
        name, arguments = "edit_file", {"path": "link/note.txt", "old_text": "outside", "new_text": "changed"}

    result = await run_tool(root, name, arguments)

    assert result.error_code == "path_outside_workspace"
    assert note.read_text(encoding="utf-8") == "outside"
    assert not (outside / "new.txt").exists()


@pytest.mark.parametrize("operation", ["read", "write", "edit"], ids=("read", "write", "edit"))
async def test_file_tools_reject_sensitive_workspace_range(tmp_path, operation) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    sensitive = root / ".artcode"
    sensitive.mkdir()
    note = sensitive / "note.txt"
    note.write_text("secret", encoding="utf-8")
    if operation == "read":
        name, arguments = "read_file", {"path": ".artcode/note.txt"}
    elif operation == "write":
        name, arguments = "write_file", {"path": ".artcode/new.txt", "content": "new"}
    else:
        name, arguments = "edit_file", {"path": ".artcode/note.txt", "old_text": "secret", "new_text": "changed"}

    result = await run_tool(root, name, arguments, sensitive=(sensitive,))

    assert result.error_code == "sensitive_path"
    assert note.read_text(encoding="utf-8") == "secret"
    assert not (sensitive / "new.txt").exists()


@pytest.mark.parametrize("operation", ["read", "write", "edit"], ids=("read", "write", "edit"))
async def test_file_tools_reject_approval_window_symlink_swap(tmp_path, operation) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    one = root / "one"
    two = root / "two"
    one.mkdir()
    two.mkdir()
    (one / "note.txt").write_text("one", encoding="utf-8")
    (two / "note.txt").write_text("two", encoding="utf-8")
    link = root / "link"
    link.symlink_to(one, target_is_directory=True)

    def retarget() -> None:
        link.unlink()
        link.symlink_to(two, target_is_directory=True)

    permission = MutatingPermissionService(retarget)
    if operation == "read":
        name, arguments = "read_file", {"path": "link/note.txt"}
    elif operation == "write":
        name, arguments = "write_file", {"path": "link/new.txt", "content": "new"}
    else:
        name, arguments = "edit_file", {"path": "link/note.txt", "old_text": "one", "new_text": "changed"}

    result = await run_tool(root, name, arguments, permission_service=permission)

    assert result.error_code == "path_target_changed"
    assert (one / "note.txt").read_text(encoding="utf-8") == "one"
    assert (two / "note.txt").read_text(encoding="utf-8") == "two"
    assert not (one / "new.txt").exists()
    assert not (two / "new.txt").exists()
