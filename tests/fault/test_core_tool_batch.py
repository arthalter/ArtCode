from __future__ import annotations

import json
from pathlib import Path
import time

from artcode._tool import LocalTools
from artcode.core.tool import PermissionMode, RunMode, ToolCall
from artcode.core.workspace import TextSlice


class SlowWorkspace:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.scope_id = "slow"

    def prepare_target(self, path, *, must_exist):
        return type("Target", (), {"scope_id": self.scope_id, "path": str(path), "must_exist": must_exist})()

    def read_text(self, target, *, start_line=None, end_line=None):
        if target.path == "fail.txt":
            raise OSError("injected read failure")
        time.sleep(0.15)
        return TextSlice(target.path, 1, 1, 1, False, None)


def call(identifier: str, path: str) -> ToolCall:
    return ToolCall(identifier, "read_file", json.dumps({"path": path}))


async def test_adjacent_observe_calls_are_concurrent_local_failure_isolated_and_results_ordered(tmp_path: Path) -> None:
    tools = LocalTools(permission_mode=PermissionMode.FULL)
    workspace = SlowWorkspace(tmp_path)
    run = tools.open_run(workspace, RunMode.CHAT)

    started = time.monotonic()
    results = await tools.execute_batch(
        run,
        (call("1", "first.txt"), call("2", "fail.txt"), call("3", "third.txt")),
    )
    elapsed = time.monotonic() - started

    assert elapsed < 0.27
    assert [item.call_id for item in results] == ["1", "2", "3"]
    assert results[0].ok is True
    assert results[1].error_code == "workspace_failure"
    assert results[2].ok is True


async def test_bad_arguments_and_unknown_tool_are_structured_local_results(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    tools = LocalTools()
    run = tools.open_run(__import__("artcode._workspace", fromlist=["LocalWorkspace"]).LocalWorkspace(root), RunMode.CHAT)

    results = await tools.execute_batch(
        run,
        (
            ToolCall("1", "read_file", "not-json"),
            ToolCall("2", "missing", "{}"),
        ),
    )

    assert [item.error_code for item in results] == ["invalid_arguments", "tool_not_found"]


async def test_single_tool_timeout_is_structured_without_cancelling_sibling_result(tmp_path: Path) -> None:
    tools = LocalTools(permission_mode=PermissionMode.FULL, tool_timeout_seconds=0.05)
    workspace = SlowWorkspace(tmp_path)
    run = tools.open_run(workspace, RunMode.CHAT)

    results = await tools.execute_batch(
        run,
        (call("1", "first.txt"), call("2", "fail.txt")),
    )

    assert [item.call_id for item in results] == ["1", "2"]
    assert results[0].error_code == "tool_timeout"
    assert results[1].error_code == "workspace_failure"
