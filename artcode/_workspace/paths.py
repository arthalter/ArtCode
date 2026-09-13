from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import uuid

from artcode.core.workspace import (
    PathOutsideWorkspace,
    SensitivePath,
    TargetChanged,
    TargetSnapshot,
    WorkspaceFailure,
)


@dataclass(frozen=True, slots=True)
class PreparedTarget(TargetSnapshot):
    resolved: Path
    identity: tuple[int, int] | None
    access_root: Path


class PathGuard:
    def __init__(
        self,
        root: Path,
        sensitive_paths: tuple[Path, ...],
        readable_paths: tuple[Path, ...] = (),
    ) -> None:
        candidate = root.expanduser()
        if not candidate.exists():
            raise ValueError(f"Workspace 不存在：{candidate}")
        if not candidate.is_dir():
            raise ValueError(f"Workspace 不是目录：{candidate}")
        self.root = candidate.resolve(strict=True)
        self.scope_id = uuid.uuid4().hex
        self.readable_paths = tuple(path.expanduser().resolve(strict=True) for path in readable_paths)
        internal = self.root / ".artcode"
        normalized = [internal.resolve(strict=False)]
        for path in sensitive_paths:
            raw = path if path.is_absolute() else self.root / path
            normalized.append(raw.expanduser().resolve(strict=False))
        self.sensitive_paths = tuple(dict.fromkeys(normalized))

    def prepare(self, raw_path: str | Path, *, must_exist: bool) -> PreparedTarget:
        text = str(raw_path)
        if not text or not text.strip():
            raise ValueError("路径不能为空。")
        requested = Path(text).expanduser()
        if not requested.is_absolute():
            requested = self.root / requested
        resolved = self._resolve(requested, must_exist=must_exist)
        access_root = self._ensure_allowed(resolved, readonly_ok=must_exist)
        if must_exist and not resolved.is_file():
            raise FileNotFoundError(f"文件不存在：{text}")
        try:
            metadata = resolved.stat()
        except FileNotFoundError:
            identity = None
        except OSError as exc:
            raise WorkspaceFailure(f"无法读取目标状态：{text}") from exc
        else:
            identity = (metadata.st_dev, metadata.st_ino)
        try:
            request_relative = requested.relative_to(self.root)
        except ValueError as exc:
            raise PathOutsideWorkspace("只读共享路径必须通过 Workspace 内声明的符号链接访问。") from exc
        display_path = (
            self.relative(resolved)
            if resolved == self.root or self.root in resolved.parents
            else request_relative.as_posix()
        )
        return PreparedTarget(
            scope_id=self.scope_id,
            path=display_path,
            must_exist=must_exist,
            resolved=resolved,
            identity=identity,
            access_root=access_root,
        )

    def verify(self, target: TargetSnapshot) -> PreparedTarget:
        if not isinstance(target, PreparedTarget) or target.scope_id != self.scope_id:
            raise TargetChanged("目标快照不属于当前 Workspace scope。")
        try:
            current = self.prepare(target.path, must_exist=target.must_exist)
        except (OSError, ValueError) as exc:
            raise TargetChanged(f"执行前目标不可用：{target.path}") from exc
        if current.resolved != target.resolved or current.identity != target.identity:
            raise TargetChanged(f"执行前目标发生变化：{target.path}")
        return current

    def relative(self, path: Path) -> str:
        try:
            relative = path.relative_to(self.root)
        except ValueError as exc:
            raise PathOutsideWorkspace(f"路径位于 Workspace 外：{path}") from exc
        return relative.as_posix() if relative.parts else "."

    def ensure_discoverable(self, path: Path) -> Path:
        resolved = path.resolve(strict=True)
        self._ensure_allowed(resolved, readonly_ok=False)
        return resolved

    def ensure_writable(self, target: PreparedTarget) -> None:
        if target.resolved != self.root and self.root not in target.resolved.parents:
            raise SensitivePath(f"只读共享路径不能写入：{target.path}")

    def directory(self, raw_path: str | Path) -> Path:
        text = str(raw_path)
        if not text or not text.strip():
            raise ValueError("工作目录不能为空。")
        requested = Path(text).expanduser()
        if not requested.is_absolute():
            requested = self.root / requested
        try:
            resolved = requested.resolve(strict=True)
        except OSError as exc:
            raise WorkspaceFailure(f"无法解析工作目录：{text}") from exc
        self._ensure_allowed(resolved, readonly_ok=False)
        if not resolved.is_dir():
            raise ValueError(f"工作目录不是目录：{text}")
        return resolved

    def _resolve(self, requested: Path, *, must_exist: bool) -> Path:
        if must_exist:
            try:
                return requested.resolve(strict=True)
            except FileNotFoundError as exc:
                raise FileNotFoundError(f"文件不存在：{requested}") from exc
            except OSError as exc:
                raise WorkspaceFailure(f"无法解析路径：{requested}") from exc
        cursor = requested
        missing: list[str] = []
        while not cursor.exists() and not cursor.is_symlink():
            if cursor.parent == cursor:
                raise PathOutsideWorkspace(f"找不到可验证的路径祖先：{requested}")
            missing.append(cursor.name)
            cursor = cursor.parent
        try:
            ancestor = cursor.resolve(strict=True)
        except OSError as exc:
            raise WorkspaceFailure(f"无法解析新文件祖先：{cursor}") from exc
        return ancestor.joinpath(*reversed(missing)).resolve(strict=False)

    def _ensure_allowed(self, path: Path, *, readonly_ok: bool) -> Path:
        roots = (self.root, *self.readable_paths) if readonly_ok else (self.root,)
        matches = [root for root in roots if path == root or root in path.parents]
        if not matches:
            raise PathOutsideWorkspace(f"路径位于 Workspace 外：{path}")
        for sensitive in self.sensitive_paths:
            if path == sensitive or sensitive in path.parents:
                raise SensitivePath(f"拒绝访问敏感路径：{path}")
        return max(matches, key=lambda item: len(item.parts))


def open_parent(root: Path, path: Path, *, create: bool) -> int:
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise PathOutsideWorkspace(f"路径位于 Workspace 外：{path}") from exc
    if not relative.parts:
        raise WorkspaceFailure("目标必须是 Workspace 内文件。")
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    current_fd = os.open(root, flags)
    try:
        for part in relative.parts[:-1]:
            try:
                child_fd = os.open(part, flags, dir_fd=current_fd)
            except FileNotFoundError:
                if not create:
                    raise
                try:
                    os.mkdir(part, 0o755, dir_fd=current_fd)
                except FileExistsError:
                    pass
                try:
                    child_fd = os.open(part, flags, dir_fd=current_fd)
                except OSError as exc:
                    raise TargetChanged(f"目录目标发生变化：{path}") from exc
            except OSError as exc:
                raise TargetChanged(f"目录目标发生变化：{path}") from exc
            os.close(current_fd)
            current_fd = child_fd
        return current_fd
    except BaseException:
        os.close(current_fd)
        raise
