from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from artcode.workspace import Workspace


class PathPolicyError(ValueError):
    pass


@dataclass(frozen=True)
class WorkspacePathPolicy:
    workspace: Workspace
    sensitive_paths: tuple[Path, ...] = ()

    def __post_init__(self) -> None:
        normalized = tuple(path.expanduser().resolve() for path in self.sensitive_paths)
        object.__setattr__(self, "sensitive_paths", normalized)

    @property
    def allowed_roots(self) -> tuple[Path, ...]:
        return (self.workspace.root,)

    def resolve_existing_path(self, raw_path: str, base_dir: Path | None = None) -> Path:
        path = self._raw_to_path(raw_path, base_dir)
        try:
            resolved = path.resolve(strict=True)
        except OSError as exc:
            raise PathPolicyError(f"无法解析路径：{path}") from exc
        return self.ensure_allowed(resolved)

    def resolve_new_file_path(self, raw_path: str, base_dir: Path | None = None) -> Path:
        path = self._raw_to_path(raw_path, base_dir)
        try:
            parent = path.parent.resolve(strict=True)
        except OSError as exc:
            raise PathPolicyError(f"无法解析新文件父目录：{path.parent}") from exc
        self.ensure_allowed(parent)
        candidate = parent / path.name
        if candidate.exists() or candidate.is_symlink():
            return self.ensure_allowed(candidate.resolve(strict=True))
        self.ensure_not_sensitive(candidate)
        return candidate

    def ensure_allowed(self, path: Path) -> Path:
        resolved = path.expanduser().resolve()
        if not self.workspace.contains(resolved):
            raise PathPolicyError(f"路径位于 Workspace 外：{resolved}")
        self.ensure_not_sensitive(resolved)
        return resolved

    def ensure_not_sensitive(self, path: Path) -> Path:
        resolved = path.expanduser().resolve()
        for sensitive in self.sensitive_paths:
            if resolved == sensitive or sensitive in resolved.parents:
                raise PathPolicyError(f"拒绝访问敏感路径：{resolved}")
        return resolved

    def is_allowed(self, path: Path) -> bool:
        try:
            self.ensure_allowed(path)
        except (OSError, ValueError):
            return False
        return True

    def relative_target(self, path: Path) -> str:
        return self.workspace.relative_path(self.ensure_allowed(path))

    def _raw_to_path(self, raw_path: str, base_dir: Path | None = None) -> Path:
        if not isinstance(raw_path, str):
            raise PathPolicyError("路径参数必须是字符串。")
        stripped = raw_path.strip()
        if not stripped:
            raise PathPolicyError("路径参数不能为空字符串。")
        path = Path(stripped).expanduser()
        if path.is_absolute():
            return path
        return (base_dir or self.workspace.root) / path
