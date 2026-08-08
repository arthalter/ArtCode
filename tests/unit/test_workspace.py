from pathlib import Path

import pytest

from artcode.workspace import ArtCodePaths, Workspace, WorkspaceError


def test_artcode_paths_create_home_and_skills(tmp_path: Path) -> None:
    paths = ArtCodePaths.create(tmp_path / "home")
    assert paths.home.is_dir()
    assert paths.skills_dir.is_dir()
    assert paths.config_file == paths.home / "config.yml"


def test_workspace_defaults_to_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert Workspace.from_path().root == tmp_path.resolve()


def test_workspace_rejects_missing_path(tmp_path: Path) -> None:
    with pytest.raises(WorkspaceError, match="不存在"):
        Workspace.from_path(tmp_path / "missing")


def test_workspace_uses_path_membership_not_string_prefix(tmp_path: Path) -> None:
    root = tmp_path / "project"
    other = tmp_path / "project-other"
    root.mkdir()
    other.mkdir()
    workspace = Workspace.from_path(root)
    assert workspace.contains(root / "file.txt")
    assert not workspace.contains(other / "file.txt")


def test_workspace_context_root_is_internal_directory(tmp_path: Path) -> None:
    workspace = Workspace.from_path(tmp_path)

    assert workspace.context_root == tmp_path / ".artcode" / "context"
