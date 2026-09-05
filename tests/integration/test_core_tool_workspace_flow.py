from __future__ import annotations

import json
from pathlib import Path

from artcode._tool import LocalTools
from artcode._workspace import LocalWorkspace
from artcode.core.tool import PermissionMode, RunMode, ToolCall


def call(identifier: str, name: str, **arguments: object) -> ToolCall:
    return ToolCall(identifier, name, json.dumps(arguments, ensure_ascii=False))


async def test_file_tools_use_one_workspace_scope_end_to_end(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    workspace = LocalWorkspace(root)
    tools = LocalTools(permission_mode=PermissionMode.EDIT)
    run = tools.open_run(workspace, RunMode.ACT)

    results = await tools.execute_batch(
        run,
        (
            call("1", "write_file", path="src/note.txt", content="hello world"),
            call("2", "edit_file", path="src/note.txt", old_text="world", new_text="ArtCode"),
            call("3", "read_file", path="src/note.txt"),
            call("4", "search_text", query="ArtCode", glob="**/*.txt"),
        ),
    )

    assert all(item.ok for item in results)
    assert results[2].content == "hello ArtCode"
    assert '"path": "src/note.txt"' in results[3].content


async def test_approval_window_target_swap_is_rechecked_by_workspace(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "note.txt"
    target.write_text("old", encoding="utf-8")
    workspace = LocalWorkspace(root)
    tools = LocalTools()

    class SwapApprover:
        async def approve(self, request):
            target.unlink()
            target.write_text("replacement", encoding="utf-8")
            from artcode.core.tool import ApprovalChoice

            return ApprovalChoice.ALLOW_ONCE

    result = await tools.execute_batch(
        tools.open_run(workspace, RunMode.ACT),
        (call("1", "write_file", path="note.txt", content="new", overwrite=True),),
        approver=SwapApprover(),
    )

    assert result[0].error_code == "target_changed"
    assert target.read_text(encoding="utf-8") == "replacement"
