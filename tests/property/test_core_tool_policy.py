from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from hypothesis import given, strategies as st

from artcode._tool import LocalTools
from artcode._workspace import LocalWorkspace
from artcode.core.tool import PermissionMode, RunMode, ToolEffect


@given(
    st.sets(st.sampled_from(["read_file", "find_files", "search_text", "write_file", "edit_file", "run_command"]))
)
def test_plan_and_skill_intersection_never_gain_effects(allowed: set[str]) -> None:
    with TemporaryDirectory() as raw:
        root = Path(raw) / "workspace"
        root.mkdir()
        tools = LocalTools(permission_mode=PermissionMode.FULL)
        run = tools.open_run(LocalWorkspace(root), RunMode.PLAN, allowed_tools=frozenset(allowed))

        assert {item.name for item in run.descriptors} <= allowed
        assert all(item.effect is ToolEffect.OBSERVE for item in run.descriptors)


@given(st.sampled_from(list(PermissionMode)), st.sampled_from(list(RunMode)))
def test_same_frozen_inputs_produce_same_snapshot(mode: PermissionMode, run_mode: RunMode) -> None:
    with TemporaryDirectory() as raw:
        root = Path(raw) / "workspace"
        root.mkdir()
        tools = LocalTools(permission_mode=mode)
        workspace = LocalWorkspace(root)

        assert tools.open_run(workspace, run_mode).descriptors == tools.open_run(workspace, run_mode).descriptors
