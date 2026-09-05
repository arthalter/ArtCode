from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import time
from typing import Callable, Iterable

from artcode.core.workspace import (
    DiscardConfirmation,
    WorktreeHandoff,
    WorktreeLease,
    WorktreePlan,
)

from .git import GitFailure, run_git, try_git
from .worktree_metadata import read_metadata, write_metadata
from .worktree_init import WorktreeInitRules, initialize, read_rules


_TASK_ID = re.compile(r"task-([0-9a-f]{8})\Z")
_COMMIT = re.compile(r"[0-9a-f]{40,64}\Z")
_SEGMENT = re.compile(r"[a-z0-9][a-z0-9._-]{0,31}\Z")


@dataclass(frozen=True, slots=True)
class FrozenWorktreePlan(WorktreePlan):
    scope_id: str
    rules: WorktreeInitRules


@dataclass(frozen=True, slots=True)
class _Status:
    tracked: int = 0
    staged: int = 0
    untracked: int = 0
    commits: int = 0
    has_upstream: bool = False
    all_pushed: bool = False
    error: str = ""

    @property
    def safe_to_remove(self) -> bool:
        return not self.error and not (self.tracked or self.staged or self.untracked or self.commits)


class WorktreeManager:
    def __init__(self, root: Path, scope_id: str, *, clock: Callable[[], float] = time.time) -> None:
        self.root = root
        self.scope_id = scope_id
        self.clock = clock
        self.managed_root = root / ".artcode" / "worktrees"
        self.metadata_root = self.managed_root / ".metadata"
        self._active: dict[str, WorktreeLease] = {}

    @property
    def active(self) -> tuple[WorktreeLease, ...]:
        return tuple(self._active.values())

    def freeze(self) -> WorktreePlan:
        try:
            top = run_git(self.root, "rev-parse", "--show-toplevel").strip()
            baseline = run_git(self.root, "rev-parse", "HEAD").strip()
        except GitFailure as exc:
            raise ValueError(f"Workspace 不是可用的 Git 仓库：{exc}") from exc
        if Path(top).resolve() != self.root or not _COMMIT.fullmatch(baseline):
            raise ValueError("Workspace 必须是带首个提交的 Git 仓库根目录。")
        rules = read_rules(self.root / ".artcode" / "worktree.yml")
        return FrozenWorktreePlan(baseline, self.scope_id, rules)

    def acquire(self, task_id: str, plan: WorktreePlan, *, name: str | None) -> WorktreeLease:
        match = _TASK_ID.fullmatch(task_id) if isinstance(task_id, str) else None
        if match is None:
            raise ValueError("任务 ID 必须是 task- 加 8 位小写十六进制字符。")
        if not isinstance(plan, FrozenWorktreePlan) or plan.scope_id != self.scope_id:
            raise ValueError("Worktree 计划不属于当前 Workspace scope。")
        if not _COMMIT.fullmatch(plan.baseline):
            raise ValueError("Worktree 基准必须是完整提交 ID。")

        selected = name if name is not None else f"agent-{match.group(1)}"
        path, branch = self._validate_name(selected, system=name is None)
        self._ensure_roots()
        self._reject_symlinks(path)
        metadata = self.metadata_root / f"{task_id}.json"
        if path.exists() or path.is_symlink() or metadata.exists() or metadata.is_symlink():
            raise FileExistsError("Worktree 目标或元数据已存在，拒绝覆盖或接管。")
        if try_git(self.root, "cat-file", "-e", f"{plan.baseline}^{{commit}}") is None:
            raise ValueError("Worktree 基准提交已不可用。")
        if try_git(self.root, "check-ignore", "--quiet", "--", ".artcode/worktrees/") is None:
            raise ValueError(".artcode/worktrees/ 必须被主仓库 .gitignore 忽略。")

        created = False
        try:
            run_git(self.root, "worktree", "add", "-b", branch, str(path), plan.baseline)
            created = True

            def configure(key: str, value: str) -> None:
                run_git(self.root, "config", "extensions.worktreeConfig", "true")
                run_git(path, "config", "--worktree", key, value)

            initialized, readable = initialize(
                self.root,
                path,
                plan.rules,
                is_ignored=self._is_ignored,
                git_config=configure,
            )
            lease = WorktreeLease(
                task_id=task_id,
                name=selected,
                path=path,
                branch=branch,
                baseline=plan.baseline,
                created_at=self.clock(),
                initialization_paths=initialized,
                readable_paths=readable,
            )
            self._configure_excludes(lease, configure)
            write_metadata(metadata, lease)
            self._active[task_id] = lease
            return lease
        except Exception:
            if created:
                self._rollback_empty(path, branch, plan.baseline)
            raise

    def inspect(self, lease: WorktreeLease) -> WorktreeHandoff:
        status = self._status(lease)
        return self._handoff(lease, status, retained=True)

    def release(self, lease: WorktreeLease) -> WorktreeHandoff:
        if self._active.get(lease.task_id) != lease:
            raise ValueError("Worktree lease 不属于当前活动任务。")
        status = self._status(lease)
        retained = True
        if status.safe_to_remove:
            try:
                self._remove_owned(lease, force=False)
                retained = False
            except Exception as exc:
                status = _Status(error=f"自动清理失败，已保留：{exc}")
        self._active.pop(lease.task_id, None)
        return self._handoff(lease, status, retained=retained)

    def discard(self, lease: WorktreeLease, confirmation: DiscardConfirmation) -> None:
        if lease.task_id in self._active:
            raise ValueError("活动 Worktree 不能危险丢弃。")
        expected = DiscardConfirmation(lease.task_id, str(lease.path), lease.branch)
        if confirmation != expected:
            raise ValueError("危险丢弃确认必须精确匹配任务、路径和分支。")
        error = self._ownership_error(lease)
        if error:
            raise ValueError(error)
        self._remove_owned(lease, force=True)

    def find(self, task_id: str) -> WorktreeLease | None:
        if task_id in self._active:
            raise ValueError("活动 Worktree 不能丢弃。")
        if _TASK_ID.fullmatch(task_id) is None:
            raise ValueError("Task ID 格式无效。")
        raw = read_metadata(self.metadata_root / f"{task_id}.json")
        if raw is None:
            return None
        lease = WorktreeLease(
            task_id=str(raw["task_id"]),
            name=str(raw["name"]),
            path=Path(str(raw["path"])),
            branch=str(raw["branch"]),
            baseline=str(raw["baseline"]),
            created_at=float(raw["created_at"]),
            initialization_paths=tuple(raw["initialization_paths"]),
            readable_paths=tuple(Path(item) for item in raw["readable_paths"]),
        )
        return lease if not self._ownership_error(lease) else None

    def list_managed(self) -> tuple[WorktreeHandoff, ...]:
        if not self.metadata_root.is_dir() or self.metadata_root.is_symlink():
            return ()
        results: list[WorktreeHandoff] = []
        for metadata in sorted(self.metadata_root.glob("task-*.json")):
            raw = read_metadata(metadata)
            if raw is None:
                continue
            lease = WorktreeLease(
                task_id=str(raw["task_id"]),
                name=str(raw["name"]),
                path=Path(str(raw["path"])),
                branch=str(raw["branch"]),
                baseline=str(raw["baseline"]),
                created_at=float(raw["created_at"]),
                initialization_paths=tuple(raw["initialization_paths"]),
                readable_paths=tuple(Path(item) for item in raw["readable_paths"]),
            )
            results.append(self._handoff(lease, self._status(lease), retained=True))
        return tuple(results)

    def cleanup(self, active_task_ids: Iterable[str], *, max_age_seconds: float) -> tuple[str, ...]:
        if max_age_seconds <= 0:
            raise ValueError("Worktree 过期时间必须为正数。")
        if not self.metadata_root.is_dir() or self.metadata_root.is_symlink():
            return ()
        active = set(active_task_ids) | set(self._active)
        removed: list[str] = []
        for metadata in sorted(self.metadata_root.glob("task-*.json")):
            raw = read_metadata(metadata)
            if raw is None:
                continue
            task_id = str(raw["task_id"])
            name = str(raw["name"])
            if task_id in active or self.clock() - float(raw["created_at"]) < max_age_seconds:
                continue
            if _TASK_ID.fullmatch(task_id) is None or name != f"agent-{task_id[-8:]}":
                continue
            lease = WorktreeLease(
                task_id=task_id,
                name=name,
                path=Path(str(raw["path"])),
                branch=str(raw["branch"]),
                baseline=str(raw["baseline"]),
                created_at=float(raw["created_at"]),
                initialization_paths=tuple(raw["initialization_paths"]),
                readable_paths=tuple(Path(item) for item in raw["readable_paths"]),
            )
            if self._status(lease).safe_to_remove:
                try:
                    self._remove_owned(lease, force=False)
                except Exception:
                    continue
                removed.append(task_id)
        return tuple(removed)

    def close(self) -> tuple[WorktreeHandoff, ...]:
        handoffs: list[WorktreeHandoff] = []
        for lease in tuple(self._active.values()):
            try:
                handoffs.append(self.release(lease))
            except Exception as exc:
                self._active.pop(lease.task_id, None)
                handoffs.append(self._handoff(lease, _Status(error=str(exc)), retained=True))
        return tuple(handoffs)

    def owns(self, lease: WorktreeLease) -> bool:
        return self._active.get(lease.task_id) == lease or not self._ownership_error(lease)

    def _status(self, lease: WorktreeLease) -> _Status:
        error = self._ownership_error(lease)
        if error:
            return _Status(error=error)
        try:
            porcelain = run_git(
                lease.path, "status", "--porcelain=v1", "-z", "--untracked-files=all"
            )
            tracked = staged = untracked = 0
            entries = [entry for entry in porcelain.split("\0") if entry]
            for entry in entries:
                code = entry[:2]
                if code == "??":
                    untracked += 1
                else:
                    if code[0] not in {" ", "?"}:
                        staged += 1
                    if code[1] not in {" ", "?"}:
                        tracked += 1
            commits = int(run_git(lease.path, "rev-list", "--count", f"{lease.baseline}..HEAD").strip())
            upstream = try_git(lease.path, "rev-parse", "--verify", "@{upstream}^{commit}")
            has_upstream = upstream is not None
            all_pushed = False
            if has_upstream:
                unpushed = try_git(lease.path, "rev-list", "--count", "@{upstream}..HEAD")
                remote = try_git(
                    lease.path, "for-each-ref", "--format=%(refname)", "--contains", "HEAD", "refs/remotes"
                )
                all_pushed = bool(
                    unpushed is not None and int(unpushed.strip()) == 0 and remote and remote.strip()
                )
            return _Status(tracked, staged, untracked, commits, has_upstream, all_pushed)
        except Exception as exc:
            return _Status(error=str(exc))

    def _ownership_error(self, lease: WorktreeLease) -> str:
        try:
            path, branch = self._validate_name(lease.name, system=lease.name.startswith("agent-"))
            metadata = self.metadata_root / f"{lease.task_id}.json"
            self._reject_symlinks(path)
            raw = read_metadata(metadata)
            expected = {
                "task_id": lease.task_id,
                "name": lease.name,
                "path": str(lease.path),
                "branch": lease.branch,
                "baseline": lease.baseline,
                "created_at": lease.created_at,
                "initialization_paths": list(lease.initialization_paths),
                "readable_paths": [str(path) for path in lease.readable_paths],
            }
            if path != lease.path or branch != lease.branch or raw is None:
                return "Worktree lease 与托管路径或元数据不匹配。"
            if any(raw.get(key) != value for key, value in expected.items()):
                return "Worktree 归属元数据与 lease 不匹配。"
            if lease.path.is_symlink() or not lease.path.is_dir() or not (lease.path / ".git").is_file():
                return "Worktree 目录或 Git 指针缺失或已被替换。"
            return ""
        except Exception as exc:
            return str(exc)

    def _remove_owned(self, lease: WorktreeLease, *, force: bool) -> None:
        error = self._ownership_error(lease)
        if error:
            raise ValueError(error)
        arguments = ["worktree", "remove"]
        if force:
            arguments.append("--force")
        arguments.append(str(lease.path))
        run_git(self.root, *arguments)
        run_git(self.root, "branch", "-D", lease.branch)
        (self.metadata_root / f"{lease.task_id}.json").unlink(missing_ok=True)

    def _ensure_roots(self) -> None:
        if self.managed_root.parent.is_symlink() or self.managed_root.is_symlink() or self.metadata_root.is_symlink():
            raise ValueError("Worktree 托管目录不能是符号链接。")
        self.metadata_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.managed_root.is_symlink() or self.metadata_root.is_symlink():
            raise ValueError("Worktree 托管目录创建期间被替换为符号链接。")
        os.chmod(self.managed_root, 0o700)
        os.chmod(self.metadata_root, 0o700)

    def _is_ignored(self, path: Path) -> bool:
        try:
            relative = path.relative_to(self.root)
        except ValueError:
            return False
        return try_git(self.root, "check-ignore", "--quiet", "--", str(relative)) == ""

    def _configure_excludes(
        self,
        lease: WorktreeLease,
        configure: Callable[[str, str], None],
    ) -> None:
        if not lease.initialization_paths:
            return
        pointer = (lease.path / ".git").read_text(encoding="utf-8")
        if not pointer.startswith("gitdir: "):
            raise ValueError("Worktree Git 指针无效。")
        git_dir = Path(pointer.removeprefix("gitdir: ").strip())
        if not git_dir.is_absolute():
            git_dir = lease.path / git_dir
        git_dir = git_dir.resolve(strict=True)
        expected_root = (self.root / ".git" / "worktrees").resolve(strict=True)
        if expected_root not in git_dir.parents:
            raise ValueError("Worktree Git 控制目录归属无效。")
        exclude = git_dir / "artcode-initialization.exclude"
        if exclude.exists() or exclude.is_symlink():
            raise FileExistsError("Worktree 初始化排除文件已存在。")
        exclude.write_text(
            "".join(f"/{item}\n" for item in lease.initialization_paths),
            encoding="utf-8",
        )
        os.chmod(exclude, 0o600)
        configure("core.excludesFile", str(exclude))

    def _validate_name(self, name: str, *, system: bool) -> tuple[Path, str]:
        if not isinstance(name, str) or not name or len(name.encode("utf-8")) > 64:
            raise ValueError("Worktree 名称无效或超过 64 字节。")
        if name.startswith(("/", "~")) or "\\" in name or "\x00" in name:
            raise ValueError("Worktree 名称包含不安全字符。")
        parts = name.split("/")
        if any(not _SEGMENT.fullmatch(part) for part in parts):
            raise ValueError("Worktree 名称每段必须是小写安全标识。")
        if system and not name.startswith("agent-"):
            raise ValueError("系统 Worktree 名称必须以 agent- 开头。")
        path = self.managed_root.joinpath(*parts)
        root = self.managed_root.resolve(strict=False)
        resolved = path.resolve(strict=False)
        if resolved == root or root not in resolved.parents:
            raise ValueError("Worktree 名称越过托管目录。")
        return path, f"worktree-{name}"

    def _reject_symlinks(self, candidate: Path) -> None:
        relative = candidate.relative_to(self.managed_root)
        cursor = self.managed_root
        if cursor.is_symlink():
            raise ValueError("Worktree 托管根不能是符号链接。")
        for part in relative.parts:
            cursor = cursor / part
            if cursor.is_symlink():
                raise ValueError(f"Worktree 路径不能包含符号链接：{cursor}")

    def _rollback_empty(self, path: Path, branch: str, baseline: str) -> None:
        try:
            porcelain = run_git(path, "status", "--porcelain=v1", "--untracked-files=all")
            commits = int(run_git(path, "rev-list", "--count", f"{baseline}..HEAD").strip())
            if porcelain or commits:
                return
            run_git(self.root, "worktree", "remove", "--force", str(path))
            run_git(self.root, "branch", "-D", branch)
        except Exception:
            return

    @staticmethod
    def _handoff(lease: WorktreeLease, status: _Status, *, retained: bool) -> WorktreeHandoff:
        return WorktreeHandoff(
            task_id=lease.task_id,
            baseline=lease.baseline,
            branch=lease.branch,
            path=lease.path,
            retained=retained,
            tracked_changes=status.tracked,
            staged_changes=status.staged,
            untracked_changes=status.untracked,
            commits_ahead=status.commits,
            has_upstream=status.has_upstream,
            all_commits_pushed=status.all_pushed,
            inspection_error=status.error,
        )
