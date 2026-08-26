from __future__ import annotations

import errno
import glob
import os
import secrets
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class FilePathPolicy(Protocol):
    @property
    def allowed_roots(self) -> tuple[Path, ...]:
        ...

    def ensure_allowed(self, path: Path) -> Path:
        ...

    def is_allowed(self, path: Path) -> bool:
        ...

    def ensure_writable(self, path: Path) -> Path:
        ...


class WorkspaceFileError(OSError):
    error_code = "file_access_error"


class WorkspaceBoundaryError(WorkspaceFileError):
    error_code = "path_outside_workspace"


class SensitivePathError(WorkspaceFileError):
    error_code = "sensitive_path"


class TargetChangedError(WorkspaceFileError):
    error_code = "path_target_changed"


class AtomicWriteError(WorkspaceFileError):
    error_code = "atomic_write_error"


@dataclass(frozen=True)
class FileTargetSnapshot:
    raw_path: str
    base_dir: Path
    approved_path: Path
    root: Path
    display_target: str
    target_identity: tuple[int, int] | None
    must_exist: bool


class WorkspaceFileAccess:
    def __init__(self, policy: FilePathPolicy) -> None:
        self.policy = policy
        self.roots = tuple(path.expanduser().resolve(strict=True) for path in policy.allowed_roots)
        if not self.roots:
            raise ValueError("WorkspaceFileAccess requires at least one root")
        self.sensitive_paths = tuple(
            path.expanduser().resolve(strict=False)
            for path in getattr(policy, "sensitive_paths", ())
        )

    def prepare_existing(self, raw_path: str, base_dir: Path | None = None) -> FileTargetSnapshot:
        raw, base = self._request(raw_path, base_dir)
        requested = self._raw_path(raw, base)
        try:
            approved = requested.resolve(strict=True)
        except OSError as exc:
            raise WorkspaceFileError(f"无法解析路径：{requested}") from exc
        self._ensure_safe(approved)
        return self._snapshot(raw, base, approved, must_exist=True)

    def prepare_file(self, raw_path: str, base_dir: Path | None = None) -> FileTargetSnapshot:
        raw, base = self._request(raw_path, base_dir)
        requested = self._raw_path(raw, base)
        approved = self._resolve_from_existing_ancestor(requested)
        self._ensure_safe(approved)
        return self._snapshot(raw, base, approved, must_exist=False)

    def verify(self, snapshot: FileTargetSnapshot) -> Path:
        try:
            current = (
                self.prepare_existing(snapshot.raw_path, snapshot.base_dir)
                if snapshot.must_exist
                else self.prepare_file(snapshot.raw_path, snapshot.base_dir)
            )
        except WorkspaceFileError as exc:
            raise TargetChangedError(f"审批后目标不可用：{exc}") from exc
        if (
            current.approved_path != snapshot.approved_path
            or current.root != snapshot.root
            or current.target_identity != snapshot.target_identity
        ):
            raise TargetChangedError(
                f"审批后路径目标发生变化：{snapshot.display_target}"
            )
        return current.approved_path

    def read_text(self, snapshot: FileTargetSnapshot) -> str:
        path = self.verify(snapshot)
        parent_fd = self._open_parent(snapshot.root, path, create=False)
        try:
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            file_fd = os.open(path.name, flags, dir_fd=parent_fd)
            try:
                metadata = os.fstat(file_fd)
                if (metadata.st_dev, metadata.st_ino) != snapshot.target_identity:
                    raise TargetChangedError(
                        f"读取前文件目标发生变化：{snapshot.display_target}"
                    )
                with os.fdopen(file_fd, "r", encoding="utf-8") as handle:
                    file_fd = -1
                    return handle.read()
            finally:
                if file_fd >= 0:
                    os.close(file_fd)
        finally:
            os.close(parent_fd)

    def read_current_text(self, path: Path) -> str:
        return self.read_text(self.prepare_existing(str(path), self._root_for(path)))

    def atomic_write_text(
        self,
        snapshot: FileTargetSnapshot,
        content: str,
        *,
        overwrite: bool,
    ) -> Path:
        path = self.verify(snapshot)
        ensure_writable = getattr(self.policy, "ensure_writable", None)
        if callable(ensure_writable):
            try:
                ensure_writable(path)
            except ValueError as exc:
                raise SensitivePathError(str(exc)) from exc
        parent_fd = self._open_parent(snapshot.root, path, create=True)
        temp_name = f".{path.name}.artcode-{secrets.token_hex(8)}.tmp"
        created_temp = False
        try:
            # Creating missing parents can expose a path component that was
            # concurrently replaced. Re-resolve before creating the temp file.
            self.verify(snapshot)
            exists = self._entry_exists(parent_fd, path.name)
            current_identity = self._entry_identity(parent_fd, path.name) if exists else None
            if current_identity != snapshot.target_identity:
                raise TargetChangedError(
                    f"写入前文件目标发生变化：{snapshot.display_target}"
                )
            if exists and not overwrite:
                raise FileExistsError(f"文件已存在，且未声明覆盖：{path}")
            if exists and self._entry_is_symlink(parent_fd, path.name):
                raise TargetChangedError(f"执行前目标变成了符号链接：{snapshot.display_target}")

            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            temp_fd = os.open(temp_name, flags, 0o600, dir_fd=parent_fd)
            created_temp = True
            try:
                with os.fdopen(temp_fd, "w", encoding="utf-8") as handle:
                    temp_fd = -1
                    handle.write(content)
                    handle.flush()
                    os.fsync(handle.fileno())
            finally:
                if temp_fd >= 0:
                    os.close(temp_fd)
            os.replace(
                temp_name,
                path.name,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
            )
            created_temp = False
            os.fsync(parent_fd)
            return path
        except (FileExistsError, TargetChangedError):
            raise
        except OSError as exc:
            raise AtomicWriteError(f"原子写入失败：{path}（{exc}）") from exc
        finally:
            if created_temp:
                try:
                    os.unlink(temp_name, dir_fd=parent_fd)
                except FileNotFoundError:
                    pass
            os.close(parent_fd)

    def find_files(self, pattern: str) -> list[Path]:
        candidates: list[Path]
        if Path(pattern).is_absolute():
            candidates = [Path(value) for value in glob.glob(pattern, recursive=True)]
        else:
            candidates = [candidate for root in self.roots for candidate in root.glob(pattern)]
        selected: set[Path] = set()
        for candidate in candidates:
            try:
                resolved = candidate.resolve(strict=True)
                self._ensure_safe(resolved)
            except (OSError, WorkspaceFileError):
                continue
            if resolved.is_file():
                selected.add(resolved)
        return sorted(selected)

    def search_files(
        self,
        target: FileTargetSnapshot | None = None,
    ) -> list[Path]:
        if target is None:
            roots = list(self.roots)
        else:
            roots = [self.verify(target)]
        selected: set[Path] = set()
        for root in roots:
            candidates = (root,) if root.is_file() else root.rglob("*")
            for candidate in candidates:
                try:
                    resolved = candidate.resolve(strict=True)
                    self._ensure_safe(resolved)
                except (OSError, WorkspaceFileError):
                    continue
                if resolved.is_file():
                    selected.add(resolved)
        return sorted(selected)

    def display_target(self, path: Path) -> str:
        return self.policy.relative_target(path)

    def _snapshot(
        self,
        raw: str,
        base: Path,
        approved: Path,
        *,
        must_exist: bool,
    ) -> FileTargetSnapshot:
        root = self._root_for(approved)
        try:
            metadata = approved.stat()
        except FileNotFoundError:
            identity = None
        except OSError as exc:
            raise WorkspaceFileError(f"无法读取目标状态：{approved}") from exc
        else:
            identity = (metadata.st_dev, metadata.st_ino)
        return FileTargetSnapshot(
            raw,
            base,
            approved,
            root,
            self.display_target(approved),
            identity,
            must_exist,
        )

    def _request(self, raw_path: str, base_dir: Path | None) -> tuple[str, Path]:
        if not isinstance(raw_path, str):
            raise WorkspaceFileError("路径参数必须是字符串。")
        raw = raw_path.strip()
        if not raw:
            raise WorkspaceFileError("路径参数不能为空字符串。")
        base = (base_dir or self.roots[0]).expanduser().resolve(strict=True)
        self._ensure_safe(base)
        return raw, base

    @staticmethod
    def _raw_path(raw: str, base: Path) -> Path:
        path = Path(raw).expanduser()
        return path if path.is_absolute() else base / path

    def _resolve_from_existing_ancestor(self, requested: Path) -> Path:
        cursor = requested
        missing: list[str] = []
        while not cursor.exists() and not cursor.is_symlink():
            if cursor.parent == cursor:
                raise WorkspaceBoundaryError(f"找不到可验证的路径祖先：{requested}")
            missing.append(cursor.name)
            cursor = cursor.parent
        try:
            ancestor = cursor.resolve(strict=True)
        except OSError as exc:
            raise WorkspaceFileError(f"无法解析新文件祖先：{cursor}") from exc
        self._ensure_safe(ancestor)
        approved = ancestor.joinpath(*reversed(missing)).resolve(strict=False)
        self._ensure_safe(approved)
        return approved

    def _ensure_safe(self, path: Path) -> Path:
        resolved = path.expanduser().resolve(strict=False)
        try:
            self._root_for(resolved)
        except WorkspaceBoundaryError:
            raise
        for sensitive in self.sensitive_paths:
            if resolved == sensitive or sensitive in resolved.parents:
                raise SensitivePathError(f"拒绝访问敏感路径：{resolved}")
        return resolved

    def _root_for(self, path: Path) -> Path:
        matches = [root for root in self.roots if path == root or root in path.parents]
        if not matches:
            raise WorkspaceBoundaryError(f"路径位于 Workspace 外：{path}")
        return max(matches, key=lambda item: len(item.parts))

    def _open_parent(self, root: Path, path: Path, *, create: bool) -> int:
        try:
            relative = path.relative_to(root)
        except ValueError as exc:
            raise WorkspaceBoundaryError(f"路径位于 Workspace 外：{path}") from exc
        if not relative.parts or relative.name in {"", ".", ".."}:
            raise WorkspaceFileError(f"目标必须是 Workspace 内的文件：{path}")
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
                    child_fd = os.open(part, flags, dir_fd=current_fd)
                except OSError as exc:
                    if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
                        raise TargetChangedError(f"路径目录目标发生变化：{path}") from exc
                    raise
                os.close(current_fd)
                current_fd = child_fd
            return current_fd
        except BaseException:
            os.close(current_fd)
            raise

    @staticmethod
    def _entry_exists(parent_fd: int, name: str) -> bool:
        try:
            os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            return False
        return True

    @staticmethod
    def _entry_is_symlink(parent_fd: int, name: str) -> bool:
        metadata = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        return stat.S_ISLNK(metadata.st_mode)

    @staticmethod
    def _entry_identity(parent_fd: int, name: str) -> tuple[int, int]:
        metadata = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        return metadata.st_dev, metadata.st_ino
