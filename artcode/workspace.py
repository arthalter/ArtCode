from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class WorkspaceError(ValueError):
    """Raised when the selected workspace cannot be used safely."""


@dataclass(frozen=True)
class ArtCodePaths:
    home: Path

    @classmethod
    def create(cls, home: Path | None = None) -> ArtCodePaths:
        root = (home or Path.home() / ".artcode").expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        paths = cls(root)
        paths.skills_dir.mkdir(parents=True, exist_ok=True)
        return paths

    @property
    def config_file(self) -> Path:
        return self.home / "config.yml"

    @property
    def user_permissions_file(self) -> Path:
        return self.home / "permissions.yml"

    @property
    def skills_dir(self) -> Path:
        return self.home / "skills"


@dataclass(frozen=True)
class Workspace:
    root: Path

    @classmethod
    def from_path(cls, path: Path | str | None = None) -> Workspace:
        candidate = Path.cwd() if path is None else Path(path)
        candidate = candidate.expanduser()
        if not candidate.exists():
            raise WorkspaceError(f"Workspace 不存在：{candidate}")
        if not candidate.is_dir():
            raise WorkspaceError(f"Workspace 不是目录：{candidate}")
        try:
            root = candidate.resolve(strict=True)
        except OSError as exc:
            raise WorkspaceError(f"无法解析 Workspace：{candidate}（{exc}）") from exc
        return cls(root)

    @property
    def project_permissions_file(self) -> Path:
        return self.root / ".artcode" / "permissions.yml"

    @property
    def project_config_file(self) -> Path:
        return self.root / ".artcode" / "config.yml"

    @property
    def local_permissions_file(self) -> Path:
        return self.root / "permissions.local.yml"

    @property
    def context_root(self) -> Path:
        return self.root / ".artcode" / "context"

    def contains(self, path: Path) -> bool:
        resolved = path.expanduser().resolve()
        return resolved == self.root or self.root in resolved.parents

    def relative_path(self, path: Path) -> str:
        resolved = path.expanduser().resolve()
        if not self.contains(resolved):
            raise WorkspaceError(f"路径位于 Workspace 外：{resolved}")
        relative = resolved.relative_to(self.root)
        return "." if not relative.parts else relative.as_posix()
