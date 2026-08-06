from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from artcode.workspace import ArtCodePaths, Workspace


@dataclass(frozen=True)
class DurablePaths:
    user_instruction: Path
    project_instruction: Path
    local_instruction: Path
    sessions_dir: Path
    user_memory_dir: Path
    project_memory_dir: Path

    @classmethod
    def from_context(cls, app_paths: ArtCodePaths, workspace: Workspace) -> "DurablePaths":
        paths = cls(
            user_instruction=app_paths.user_instruction_file,
            project_instruction=workspace.project_instruction_file,
            local_instruction=workspace.local_instruction_file,
            sessions_dir=workspace.sessions_dir,
            user_memory_dir=app_paths.user_memory_dir,
            project_memory_dir=workspace.project_memory_dir,
        )
        for directory in (paths.sessions_dir, paths.user_memory_dir, paths.project_memory_dir):
            _ensure_private_directory(directory)
        return paths


def _ensure_private_directory(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError:
        # A read-only or ACL-managed filesystem will fail later at the actual
        # write point with the concrete path in the error.
        pass
