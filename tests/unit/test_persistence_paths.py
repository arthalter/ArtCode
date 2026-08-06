from __future__ import annotations

import stat
from pathlib import Path

from artcode.persistence import DurablePaths
from artcode.workspace import ArtCodePaths, Workspace
from artcode.tools import WorkspacePathPolicy


def test_durable_paths_use_existing_artcode_namespace(tmp_path: Path) -> None:
    home = tmp_path / "user-home"
    project = tmp_path / "project"
    project.mkdir()

    paths = DurablePaths.from_context(ArtCodePaths.create(home), Workspace.from_path(project))

    assert paths.user_instruction == home / "instructions.md"
    assert paths.project_instruction == project / "ARTCODE.md"
    assert paths.local_instruction == project / ".artcode" / "instructions.md"
    assert paths.sessions_dir == project / ".artcode" / "sessions"
    assert paths.user_memory_dir == home / "memory"
    assert paths.project_memory_dir == project / ".artcode" / "memory"
    assert ".mewcode" not in "\n".join(str(value) for value in paths.__dict__.values())
    assert not paths.user_instruction.exists()
    assert not paths.project_instruction.exists()
    assert not paths.local_instruction.exists()


def test_durable_private_directories_are_mode_0700(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    paths = DurablePaths.from_context(
        ArtCodePaths.create(tmp_path / "home"), Workspace.from_path(project)
    )

    for directory in (paths.sessions_dir, paths.user_memory_dir, paths.project_memory_dir):
        assert directory.is_dir()
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700


def test_workspace_policy_rejects_project_persistence_paths(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    workspace = Workspace.from_path(project)
    paths = DurablePaths.from_context(ArtCodePaths.create(tmp_path / "home"), workspace)
    paths.project_instruction.write_text("rules", encoding="utf-8")
    paths.local_instruction.write_text("local", encoding="utf-8")
    policy = WorkspacePathPolicy(
        workspace,
        (
            paths.project_instruction,
            paths.local_instruction,
            paths.sessions_dir,
            paths.project_memory_dir,
        ),
    )

    assert not policy.is_allowed(paths.project_instruction)
    assert not policy.is_allowed(paths.local_instruction)
    assert not policy.is_allowed(paths.sessions_dir)
    assert not policy.is_allowed(paths.project_memory_dir)
