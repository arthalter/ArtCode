from __future__ import annotations

import hashlib
import os
import shutil
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .models import WorkspaceChange


class WorkspaceSafetyError(ValueError):
    pass


@dataclass(frozen=True)
class FileSnapshot:
    kind: str
    sha256: str | None
    bytes: int | None


def validate_relative_path(value: str, *, label: str = "path") -> PurePosixPath:
    if not isinstance(value, str) or not value:
        raise WorkspaceSafetyError(f"{label} 必须是非空相对路径")
    if "\x00" in value:
        raise WorkspaceSafetyError(f"{label} 不能包含 NUL")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise WorkspaceSafetyError(f"{label} 必须位于工作区内：{value}")
    if value.startswith("~"):
        raise WorkspaceSafetyError(f"{label} 不能使用用户目录缩写：{value}")
    return path


def resolve_workspace_path(root: Path, relative: str, *, must_exist: bool = False) -> Path:
    safe = validate_relative_path(relative)
    root_resolved = root.resolve(strict=True)
    candidate = root_resolved.joinpath(*safe.parts)
    resolved = candidate.resolve(strict=must_exist)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise WorkspaceSafetyError(f"路径越过工作区边界：{relative}") from exc
    return resolved


def validate_fixture_tree(fixture: Path, benchmark_dir: Path) -> Path:
    if fixture.is_symlink():
        raise WorkspaceSafetyError(f"Fixture 不能是符号链接：{fixture}")
    resolved_benchmark = benchmark_dir.resolve(strict=True)
    resolved_fixture = fixture.resolve(strict=True)
    try:
        resolved_fixture.relative_to(resolved_benchmark)
    except ValueError as exc:
        raise WorkspaceSafetyError(f"Fixture 必须位于 Benchmark 目录内：{fixture}") from exc
    if not resolved_fixture.is_dir():
        raise WorkspaceSafetyError(f"Fixture 必须是目录：{fixture}")
    for item in resolved_fixture.rglob("*"):
        if item.is_symlink():
            target = item.resolve(strict=True)
            try:
                target.relative_to(resolved_fixture)
            except ValueError as exc:
                raise WorkspaceSafetyError(f"Fixture 包含越界符号链接：{item}") from exc
    return resolved_fixture


def copy_fixture(fixture: Path, destination: Path) -> None:
    if destination.exists():
        raise WorkspaceSafetyError(f"目标工作区已经存在：{destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(fixture, destination, symlinks=True)
    _validate_runtime_tree(destination)


def snapshot_workspace(
    root: Path,
    *,
    excluded_roots: tuple[str, ...] = (),
) -> dict[str, FileSnapshot]:
    root_resolved = root.resolve(strict=True)
    _validate_runtime_tree(root_resolved)
    result: dict[str, FileSnapshot] = {}
    for path in sorted(root_resolved.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(root_resolved).as_posix()
        if any(
            relative == excluded or relative.startswith(f"{excluded}/")
            for excluded in excluded_roots
        ):
            continue
        stat = path.lstat()
        if path.is_symlink():
            target = os.readlink(path)
            result[relative] = FileSnapshot(
                "symlink",
                hashlib.sha256(target.encode("utf-8", errors="replace")).hexdigest(),
                len(target.encode("utf-8", errors="replace")),
            )
        elif path.is_file():
            result[relative] = FileSnapshot(
                "file",
                _sha256_file(path),
                stat.st_size,
            )
        elif path.is_dir():
            result[relative] = FileSnapshot("directory", None, None)
        else:
            raise WorkspaceSafetyError(f"工作区包含不支持的文件类型：{relative}")
    return result


def diff_snapshots(
    before: dict[str, FileSnapshot],
    after: dict[str, FileSnapshot],
) -> tuple[WorkspaceChange, ...]:
    changes: list[WorkspaceChange] = []
    for path in sorted(set(before) | set(after)):
        old = before.get(path)
        new = after.get(path)
        if old == new:
            continue
        if old is None:
            kind = "created"
        elif new is None:
            kind = "deleted"
        else:
            kind = "modified"
        changes.append(
            WorkspaceChange(
                path=path,
                kind=kind,
                before_sha256=old.sha256 if old else None,
                after_sha256=new.sha256 if new else None,
                before_bytes=old.bytes if old else None,
                after_bytes=new.bytes if new else None,
            )
        )
    return tuple(changes)


def _validate_runtime_tree(root: Path) -> None:
    root_resolved = root.resolve(strict=True)
    for path in root_resolved.rglob("*"):
        if not path.is_symlink():
            continue
        try:
            target = path.resolve(strict=True)
        except FileNotFoundError as exc:
            raise WorkspaceSafetyError(f"工作区包含断裂符号链接：{path}") from exc
        try:
            target.relative_to(root_resolved)
        except ValueError as exc:
            raise WorkspaceSafetyError(f"工作区包含越界符号链接：{path}") from exc


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "FileSnapshot",
    "WorkspaceSafetyError",
    "copy_fixture",
    "diff_snapshots",
    "resolve_workspace_path",
    "snapshot_workspace",
    "validate_fixture_tree",
    "validate_relative_path",
]
