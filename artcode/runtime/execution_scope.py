from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from artcode.permissions import PermissionSnapshot
from artcode.workspace import Workspace


@dataclass(frozen=True)
class ExecutionScope:
    """The explicit filesystem and permission boundary of one agent runtime."""

    agent_id: str
    workspace: Workspace
    permission: PermissionSnapshot
    is_subagent: bool = False
    managed_worktrees_root: Path | None = None
    readonly_paths: tuple[Path, ...] = ()

    def __post_init__(self) -> None:
        if not self.agent_id.strip():
            raise ValueError("execution scope requires an agent id")
        object.__setattr__(self, "readonly_paths", tuple(path.expanduser().resolve() for path in self.readonly_paths))
        if self.managed_worktrees_root is not None:
            object.__setattr__(self, "managed_worktrees_root", self.managed_worktrees_root.expanduser().resolve(strict=False))
