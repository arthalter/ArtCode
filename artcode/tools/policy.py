from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AllowedPathPolicy:
    allowed_roots: tuple[Path, ...]

    def __post_init__(self) -> None:
        if not self.allowed_roots:
            raise ValueError("allowed_roots must not be empty.")
        normalized = tuple(path.expanduser().resolve() for path in self.allowed_roots)
        object.__setattr__(self, "allowed_roots", normalized)

    def resolve_existing_path(self, raw_path: str, base_dir: Path | None = None) -> Path:
        path = self._raw_to_path(raw_path, base_dir)
        resolved = path.expanduser().resolve()
        return self.ensure_allowed(resolved)

    def resolve_new_file_path(self, raw_path: str, base_dir: Path | None = None) -> Path:
        path = self._raw_to_path(raw_path, base_dir)
        parent = path.parent.expanduser().resolve()
        self.ensure_allowed(parent)
        return parent / path.name

    def ensure_allowed(self, path: Path) -> Path:
        resolved = path.expanduser().resolve()
        if not self.is_allowed(resolved):
            raise ValueError(f"路径不在允许目录内：{resolved}")
        return resolved

    def is_allowed(self, path: Path) -> bool:
        resolved = path.expanduser().resolve()
        return any(resolved == root or root in resolved.parents for root in self.allowed_roots)

    def _raw_to_path(self, raw_path: str, base_dir: Path | None = None) -> Path:
        if not isinstance(raw_path, str):
            raise ValueError("路径参数必须是字符串。")
        stripped = raw_path.strip()
        if not stripped:
            raise ValueError("路径参数不能为空。")

        path = Path(stripped).expanduser()
        if path.is_absolute():
            return path

        base = base_dir or self.allowed_roots[0]
        return base / path
