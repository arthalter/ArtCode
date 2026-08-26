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
    readonly_paths: tuple[Path, ...] = ()

    def __post_init__(self) -> None:
        normalized = tuple(path.expanduser().resolve() for path in self.sensitive_paths)
        object.__setattr__(self, "sensitive_paths", normalized)
        readonly = tuple(path.expanduser().resolve() for path in self.readonly_paths)
        object.__setattr__(self, "readonly_paths", readonly)

    @property
    def allowed_roots(self) -> tuple[Path, ...]:
        return (self.workspace.root, *self.readonly_paths)

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
        if not any(resolved == root or root in resolved.parents for root in self.allowed_roots):
            raise PathPolicyError(f"路径位于 Workspace 外：{resolved}")
        self.ensure_not_sensitive(resolved)
        return resolved

    def ensure_not_sensitive(self, path: Path) -> Path:
        resolved = path.expanduser().resolve()
        for sensitive in self.sensitive_paths:
            if resolved == sensitive or sensitive in resolved.parents:
                raise PathPolicyError(f"拒绝访问敏感路径：{resolved}")
        return resolved

    def ensure_writable(self, path: Path) -> Path:
        resolved = self.ensure_allowed(path)
        for readonly in self.readonly_paths:
            if resolved == readonly or readonly in resolved.parents:
                raise PathPolicyError(f"拒绝写入共享只读路径：{resolved}")
        return resolved

    def is_allowed(self, path: Path) -> bool:
        try:
            self.ensure_allowed(path)
        except (OSError, ValueError):
            return False
        return True

    def relative_target(self, path: Path) -> str:
        resolved = self.ensure_allowed(path)
        if self.workspace.contains(resolved):
            return self.workspace.relative_path(resolved)
        for readonly in self.readonly_paths:
            if resolved == readonly or readonly in resolved.parents:
                relative = resolved.relative_to(readonly)
                suffix = "." if not relative.parts else relative.as_posix()
                return f"共享只读依赖/{readonly.name}/{suffix}"
        raise PathPolicyError(f"路径位于 Workspace 外：{resolved}")

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
