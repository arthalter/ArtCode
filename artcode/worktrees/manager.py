from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path
from typing import Iterable

from .initializer import initialize_worktree, read_rules
from .metadata import read_metadata, remove_metadata, write_metadata
from .models import WorktreeHandoff, WorktreeLease, WorktreeStatus
from .naming import validate_worktree_name


_TASK_ID = re.compile(r"^task-([0-9a-f]{8})$")
_SYSTEM_NAME = re.compile(r"^agent-([0-9a-f]{8})$")
_COMMIT_ID = re.compile(r"^[0-9a-f]{40,64}$")


class WorktreeManager:
    """Own system-created worktrees without ever falling back to the main checkout."""

    def __init__(self, workspace_root: Path, *, clock=time.time) -> None:
        self.workspace_root = workspace_root.expanduser().resolve()
        self.managed_root = self.workspace_root / ".artcode" / "worktrees"
        self.metadata_root = self.managed_root / ".metadata"
        self.clock = clock
        self._active_task_ids: set[str] = set()
        self.last_cleanup_diagnostics: tuple[str, ...] = ()

    @property
    def active_task_ids(self) -> frozenset[str]:
        return frozenset(self._active_task_ids)

    def capture_baseline(self) -> str:
        root = self._git("rev-parse", "--show-toplevel", cwd=self.workspace_root).strip()
        if Path(root).resolve() != self.workspace_root:
            raise ValueError("Workspace 必须是 Git 仓库根目录才能创建 Worktree。")
        baseline = self._git("rev-parse", "HEAD", cwd=self.workspace_root).strip()
        if not _COMMIT_ID.fullmatch(baseline):
            raise ValueError("Git 仓库没有可用的完整提交 ID。")
        return baseline

    def capture_initialization_rules(self):
        return read_rules(self.workspace_root / ".artcode" / "worktree.yml")

    def acquire(
        self,
        task_id: str,
        baseline: str,
        *,
        name: str | None = None,
        rules=None,
    ) -> WorktreeLease:
        match = _TASK_ID.fullmatch(task_id) if isinstance(task_id, str) else None
        if match is None:
            raise ValueError("任务 ID 必须是 task- 加 8 位小写十六进制字符。")
        if not isinstance(baseline, str) or not _COMMIT_ID.fullmatch(baseline):
            raise ValueError("Worktree 基准必须是完整的小写十六进制提交 ID。")

        if name is None:
            selected = validate_worktree_name(
                self.managed_root, f"agent-{match.group(1)}", system=True
            )
        else:
            selected = validate_worktree_name(self.managed_root, name)

        self._ensure_managed_root()
        self._reject_candidate_symlinks(selected.path)
        metadata_path = self.metadata_root / f"{task_id}.json"
        if metadata_path.parent.is_symlink() or metadata_path.is_symlink():
            raise ValueError("Worktree 归属元数据路径不能是符号链接。")

        existing = self._recover(task_id, selected, baseline, metadata_path)
        if existing is not None:
            self._active_task_ids.add(task_id)
            return existing
        if (
            selected.path.exists()
            or selected.path.is_symlink()
            or metadata_path.exists()
            or metadata_path.is_symlink()
        ):
            raise FileExistsError("Worktree 目标或元数据已存在且不能安全恢复。")

        self._ensure_git_repository(baseline)
        if not self._is_ignored(self.managed_root):
            raise ValueError(".artcode/worktrees/ 必须被主仓库 .gitignore 忽略。")

        created = False
        initialization_paths: tuple[str, ...] = ()
        try:
            self._git(
                "worktree",
                "add",
                "-b",
                selected.branch,
                str(selected.path),
                baseline,
                cwd=self.workspace_root,
            )
            created = True
            selected_rules = rules if rules is not None else self.capture_initialization_rules()
            initialization_paths = tuple(
                dict.fromkeys((*selected_rules.copy, *selected_rules.symlink))
            )
            lease = WorktreeLease(
                task_id,
                selected.value,
                selected.path,
                selected.branch,
                baseline,
                self.workspace_root,
                metadata_path,
                self.clock(),
                initialization_paths,
            )

            def configure_worktree(key: str, value: str) -> None:
                self._git(
                    "config", "extensions.worktreeConfig", "true", cwd=self.workspace_root
                )
                self._git("config", "--worktree", key, value, cwd=selected.path)

            initialize_worktree(
                self.workspace_root,
                selected.path,
                selected_rules,
                is_ignored=self._is_ignored,
                git_config=configure_worktree,
            )
            self._configure_initialization_excludes(
                lease, initialization_paths, configure_worktree
            )
            write_metadata(lease)
            self._active_task_ids.add(task_id)
            return lease
        except Exception:
            if created:
                self._remove_new_empty(
                    selected.path,
                    selected.branch,
                    baseline,
                    initialization_paths,
                )
            raise

    def find(self, task_id: str) -> WorktreeLease | None:
        """Locate a system worktree by task id without mutating anything.

        Only worktrees with trusted ownership metadata and a name that
        passes path validation can be located; everything else is
        reported as not found rather than being adopted.
        """
        if not isinstance(task_id, str) or _TASK_ID.fullmatch(task_id) is None:
            raise ValueError("任务 ID 必须是 task- 加 8 位小写十六进制字符。")
        if task_id in self._active_task_ids:
            raise ValueError("任务仍在运行，不能丢弃其 Worktree。")
        metadata_path = self.metadata_root / f"{task_id}.json"
        if metadata_path.is_symlink() or not metadata_path.is_file():
            return None
        raw = read_metadata(metadata_path)
        if raw is None:
            return None
        name = str(raw["name"])
        try:
            selected = validate_worktree_name(
                self.managed_root, name, system=bool(_SYSTEM_NAME.fullmatch(name))
            )
        except ValueError:
            return None
        if selected.branch != str(raw["branch"]) or selected.path != Path(str(raw["path"])):
            return None
        lease = WorktreeLease(
            task_id,
            selected.value,
            selected.path,
            selected.branch,
            str(raw["baseline"]),
            self.workspace_root,
            metadata_path,
            float(raw["created_at"]),
            tuple(raw["initialization_paths"]),
        )
        if self._ownership_error(lease):
            return None
        return lease

    def discard(self, task_id: str) -> None:
        """Permanently drop a retained system worktree and its branch.

        This is the only path that removes worktrees containing
        uncommitted changes or unpushed commits. It must be invoked by a
        direct user action after an explicit confirmation; models and
        sub-agents have no access to it.
        """
        lease = self.find(task_id)
        if lease is None:
            raise KeyError(f"找不到可丢弃的系统 Worktree：{task_id}")
        error = self._ownership_error(lease)
        if error:
            raise ValueError(error)
        try:
            self._git("worktree", "remove", "--force", str(lease.path), cwd=self.workspace_root)
        finally:
            self._active_task_ids.discard(task_id)
        try:
            self._git("branch", "-D", lease.branch, cwd=self.workspace_root)
        except Exception:
            # Keep metadata so a later scan can diagnose the residual branch.
            raise
        remove_metadata(lease.metadata_path)

    def handoff(self, lease: WorktreeLease) -> WorktreeHandoff:
        try:
            status = self.status(lease)
            retained = not status.safe_to_remove
            if not retained:
                try:
                    self._remove_owned(lease, delete_branch=True)
                except Exception as exc:
                    retained = True
                    status = WorktreeStatus(
                        status.tracked_changes,
                        status.staged_changes,
                        status.untracked_changes,
                        status.commits_ahead,
                        status.has_upstream,
                        status.all_commits_pushed,
                        f"自动清理失败，已保留可验证资源：{exc}",
                    )
            message = status.inspection_error or (
                "基准只包含入队时提交，不包含主工作区未提交修改。"
            )
            return WorktreeHandoff(
                baseline=lease.baseline,
                branch=lease.branch,
                path=lease.path,
                retained=retained,
                tracked_changes=status.tracked_changes,
                staged_changes=status.staged_changes,
                untracked_changes=status.untracked_changes,
                commits_ahead=status.commits_ahead,
                has_upstream=status.has_upstream,
                all_commits_pushed=status.all_commits_pushed,
                message=message,
            )
        finally:
            self._active_task_ids.discard(lease.task_id)

    def status(self, lease: WorktreeLease) -> WorktreeStatus:
        ownership_error = self._ownership_error(lease)
        if ownership_error:
            return WorktreeStatus(0, 0, 0, 0, False, False, ownership_error)
        try:
            porcelain = self._git(
                "status", "--porcelain=v1", "-z", "--untracked-files=all", cwd=lease.path
            )
            tracked, staged, untracked = _porcelain_counts(
                porcelain, lease.initialization_paths
            )

            commits_ahead = int(
                self._git(
                    "rev-list", "--count", f"{lease.baseline}..HEAD", cwd=lease.path
                ).strip()
            )
            upstream = self._try_git(
                "rev-parse", "--verify", "@{upstream}^{commit}", cwd=lease.path
            )
            has_upstream = upstream is not None
            all_commits_pushed = False
            if has_upstream:
                unpushed = self._try_git(
                    "rev-list", "--count", "@{upstream}..HEAD", cwd=lease.path
                )
                remote_refs = self._try_git(
                    "for-each-ref",
                    "--format=%(refname)",
                    "--contains",
                    "HEAD",
                    "refs/remotes",
                    cwd=lease.path,
                )
                all_commits_pushed = (
                    unpushed is not None
                    and int(unpushed.strip()) == 0
                    and remote_refs is not None
                    and bool(remote_refs.strip())
                )
            return WorktreeStatus(
                tracked,
                staged,
                untracked,
                commits_ahead,
                has_upstream,
                all_commits_pushed,
            )
        except Exception as exc:
            return WorktreeStatus(0, 0, 0, 0, False, False, str(exc))

    def cleanup_expired(
        self,
        active_task_ids: Iterable[str],
        *,
        max_age_seconds: float = 24 * 3600,
    ) -> tuple[str, ...]:
        active = set(active_task_ids) | self._active_task_ids
        removed: list[str] = []
        diagnostics: list[str] = []
        if not self.metadata_root.exists() or self.metadata_root.is_symlink():
            self.last_cleanup_diagnostics = ()
            return ()

        for metadata_path in sorted(self.metadata_root.glob("*.json")):
            raw = read_metadata(metadata_path)
            if raw is None:
                diagnostics.append(f"保留损坏或不可信元数据：{metadata_path}")
                continue
            task_id = str(raw["task_id"])
            name = str(raw["name"])
            task_match = _TASK_ID.fullmatch(task_id)
            name_match = _SYSTEM_NAME.fullmatch(name)
            if (
                task_match is None
                or name_match is None
                or task_match.group(1) != name_match.group(1)
                or str(raw["branch"]) != f"worktree-{name}"
            ):
                diagnostics.append(f"保留非系统临时 Worktree：{metadata_path}")
                continue
            if task_id in active:
                diagnostics.append(f"保留活动 Worktree：{task_id}")
                continue
            if self.clock() - float(raw["created_at"]) < max_age_seconds:
                continue

            lease = WorktreeLease(
                task_id,
                name,
                Path(str(raw["path"])),
                str(raw["branch"]),
                str(raw["baseline"]),
                Path(str(raw["main_workspace"])),
                metadata_path,
                float(raw["created_at"]),
                tuple(raw["initialization_paths"]),
            )
            status = self.status(lease)
            if status.inspection_error:
                diagnostics.append(f"保留 {task_id}：{status.inspection_error}")
                continue
            if status.has_file_changes:
                diagnostics.append(f"保留 {task_id}：包含未提交文件变化。")
                continue

            delete_branch = status.commits_ahead == 0
            pushed_commit_handoff = (
                status.commits_ahead > 0
                and status.has_upstream
                and status.all_commits_pushed
            )
            if not delete_branch and not pushed_commit_handoff:
                diagnostics.append(f"保留 {task_id}：包含未安全交接的本地提交。")
                continue
            try:
                self._remove_owned(lease, delete_branch=delete_branch)
                removed.append(task_id)
            except Exception as exc:
                diagnostics.append(f"保留 {task_id}：清理失败：{exc}")

        self.last_cleanup_diagnostics = tuple(diagnostics)
        return tuple(removed)

    def _recover(self, task_id: str, selected, baseline: str, metadata_path: Path) -> WorktreeLease | None:
        if not selected.path.exists() and not metadata_path.exists():
            return None
        self._reject_candidate_symlinks(selected.path)
        if selected.path.is_symlink() or metadata_path.is_symlink():
            raise ValueError("拒绝恢复含符号链接的 Worktree。")
        raw = read_metadata(metadata_path)
        git_pointer = selected.path / ".git"
        if (
            raw is None
            or not selected.path.is_dir()
            or git_pointer.is_symlink()
            or not git_pointer.is_file()
        ):
            raise ValueError("已有 Worktree 缺少可信归属元数据。")
        expected = {
            "task_id": task_id,
            "name": selected.value,
            "path": str(selected.path),
            "branch": selected.branch,
            "baseline": baseline,
            "main_workspace": str(self.workspace_root),
        }
        if any(raw[key] != value for key, value in expected.items()):
            raise ValueError("已有 Worktree 归属与本次任务不匹配。")

        pointer = git_pointer.read_text(encoding="utf-8", errors="strict")
        if not pointer.startswith("gitdir: "):
            raise ValueError("已有 Worktree 的 .git 指针无效。")
        literal_git_dir = Path(pointer.removeprefix("gitdir: ").strip())
        if not literal_git_dir.is_absolute():
            literal_git_dir = selected.path / literal_git_dir
        if literal_git_dir.is_symlink():
            raise ValueError("已有 Worktree 的 Git 目录不能是符号链接。")
        git_dir = literal_git_dir.resolve(strict=True)
        common_git_dir = self.workspace_root / ".git"
        if common_git_dir.is_symlink() or not common_git_dir.is_dir():
            raise ValueError("主仓库 Git 目录不可信。")
        worktree_git_root = (common_git_dir / "worktrees").resolve(strict=True)
        if worktree_git_root not in git_dir.parents or not git_dir.is_dir():
            raise ValueError("已有 Worktree 的 Git 目录不属于托管仓库。")

        head_path = git_dir / "HEAD"
        common_path = git_dir / "commondir"
        if (
            head_path.is_symlink()
            or common_path.is_symlink()
            or not head_path.is_file()
            or not common_path.is_file()
        ):
            raise ValueError("已有 Worktree 的 Git 控制文件无效。")
        head = head_path.read_text(encoding="utf-8", errors="strict").strip()
        if head != f"ref: refs/heads/{selected.branch}":
            raise ValueError("已有 Worktree 的分支归属不匹配。")
        resolved_common = (
            git_dir / common_path.read_text(encoding="utf-8", errors="strict").strip()
        ).resolve(strict=True)
        if resolved_common != common_git_dir.resolve(strict=True):
            raise ValueError("已有 Worktree 不属于当前 Git 仓库。")
        initialization_paths = tuple(raw["initialization_paths"])
        unknown = _unknown_worktree_paths(
            selected.path, git_dir, common_git_dir, initialization_paths
        )
        if unknown:
            raise ValueError(
                "已有 Worktree 含未知普通文件，拒绝接管："
                + "、".join(unknown[:5])
            )
        return WorktreeLease(
            task_id,
            selected.value,
            selected.path,
            selected.branch,
            baseline,
            self.workspace_root,
            metadata_path,
            float(raw["created_at"]),
            initialization_paths,
        )

    def _ownership_error(self, lease: WorktreeLease) -> str:
        try:
            selected = validate_worktree_name(
                self.managed_root,
                lease.name,
                system=bool(_SYSTEM_NAME.fullmatch(lease.name)),
            )
            expected_metadata = self.metadata_root / f"{lease.task_id}.json"
            if (
                lease.main_workspace.resolve() != self.workspace_root
                or selected.path != lease.path
                or selected.branch != lease.branch
                or lease.metadata_path != expected_metadata
            ):
                return "Worktree 租约字段与当前管理器不匹配。"
            self._reject_candidate_symlinks(lease.path)
            raw = read_metadata(expected_metadata)
            if raw is None:
                return "Worktree 归属元数据缺失或损坏。"
            expected = {
                "task_id": lease.task_id,
                "name": lease.name,
                "path": str(lease.path),
                "branch": lease.branch,
                "baseline": lease.baseline,
                "main_workspace": str(self.workspace_root),
                "created_at": lease.created_at,
                "initialization_paths": list(lease.initialization_paths),
            }
            if any(raw.get(key) != value for key, value in expected.items()):
                return "Worktree 归属元数据与租约不匹配。"
            if lease.path.is_symlink() or not lease.path.is_dir():
                return "Worktree 目录缺失或已被替换。"
            return ""
        except Exception as exc:
            return str(exc)

    def _configure_initialization_excludes(
        self,
        lease: WorktreeLease,
        initialization_paths: tuple[str, ...],
        configure_worktree,
    ) -> None:
        if not initialization_paths:
            return
        pointer = (lease.path / ".git").read_text(encoding="utf-8", errors="strict")
        if not pointer.startswith("gitdir: "):
            raise ValueError("新 Worktree 的 .git 指针无效。")
        literal = Path(pointer.removeprefix("gitdir: ").strip())
        if not literal.is_absolute():
            literal = lease.path / literal
        linked_git = literal.resolve(strict=True)
        common_worktrees = (self.workspace_root / ".git" / "worktrees").resolve(
            strict=True
        )
        if common_worktrees not in linked_git.parents or linked_git.is_symlink():
            raise ValueError("新 Worktree 的 Git 控制目录归属无效。")
        exclude_path = linked_git / "artcode-initialization.exclude"
        if exclude_path.exists() or exclude_path.is_symlink():
            raise FileExistsError("Worktree 初始化排除文件已存在。")
        lines = [f"/{_escape_gitignore_path(value)}" for value in initialization_paths]
        exclude_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.chmod(exclude_path, 0o600)
        configure_worktree("core.excludesFile", str(exclude_path))

    def _remove_owned(self, lease: WorktreeLease, *, delete_branch: bool) -> None:
        ownership_error = self._ownership_error(lease)
        if ownership_error:
            raise ValueError(ownership_error)
        self._git("worktree", "remove", str(lease.path), cwd=self.workspace_root)
        if delete_branch:
            self._git("branch", "-D", lease.branch, cwd=self.workspace_root)
        remove_metadata(lease.metadata_path)

    def _ensure_managed_root(self) -> None:
        artcode_dir = self.managed_root.parent
        if (
            artcode_dir.is_symlink()
            or self.managed_root.is_symlink()
            or self.metadata_root.is_symlink()
        ):
            raise ValueError("Worktree 托管目录不能是符号链接。")
        self.managed_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.metadata_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.managed_root.is_symlink() or self.metadata_root.is_symlink():
            raise ValueError("Worktree 托管目录创建期间被替换。")
        os.chmod(self.managed_root, 0o700)
        os.chmod(self.metadata_root, 0o700)

    def _reject_candidate_symlinks(self, candidate: Path) -> None:
        try:
            relative = candidate.relative_to(self.managed_root)
        except ValueError as exc:
            raise ValueError("Worktree 路径越过托管根。") from exc
        cursor = self.managed_root
        if cursor.is_symlink():
            raise ValueError("Worktree 托管根不能是符号链接。")
        for part in relative.parts:
            cursor = cursor / part
            if cursor.is_symlink():
                raise ValueError(f"Worktree 路径不能包含符号链接：{cursor}")

    def _ensure_git_repository(self, baseline: str) -> None:
        root = self._git("rev-parse", "--show-toplevel", cwd=self.workspace_root).strip()
        if Path(root).resolve() != self.workspace_root:
            raise ValueError("Workspace 必须是 Git 仓库根目录才能创建 Worktree。")
        self._git("cat-file", "-e", f"{baseline}^{{commit}}", cwd=self.workspace_root)

    def _is_ignored(self, path: Path) -> bool:
        try:
            relative = path.relative_to(self.workspace_root)
        except ValueError:
            return False
        result = self._try_git(
            "check-ignore", "--quiet", "--", str(relative), cwd=self.workspace_root
        )
        return result == ""

    def _remove_new_empty(
        self,
        path: Path,
        branch: str,
        baseline: str,
        initialization_paths: tuple[str, ...],
    ) -> None:
        try:
            self._reject_candidate_symlinks(path)
            if not path.is_dir() or path.is_symlink():
                return
            porcelain = self._git(
                "status", "--porcelain=v1", "-z", "--untracked-files=all", cwd=path
            )
            commits = int(
                self._git("rev-list", "--count", f"{baseline}..HEAD", cwd=path).strip()
            )
            if any(_porcelain_counts(porcelain, initialization_paths)) or commits:
                return
            self._git("worktree", "remove", "--force", str(path), cwd=self.workspace_root)
            self._git("branch", "-D", branch, cwd=self.workspace_root)
        except Exception:
            return

    def _git(self, *args: str, cwd: Path) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or f"git {' '.join(args)} failed")
        return result.stdout

    def _try_git(self, *args: str, cwd: Path) -> str | None:
        try:
            return self._git(*args, cwd=cwd)
        except (OSError, RuntimeError, subprocess.SubprocessError):
            return None


def _unknown_worktree_paths(
    root: Path,
    git_dir: Path,
    common_git_dir: Path,
    initialization_paths: tuple[str, ...],
) -> tuple[str, ...]:
    tracked, gitlinks = _read_index_paths(git_dir / "index", common_git_dir)
    initialized: tuple[Path, ...] = tuple(Path(value) for value in initialization_paths)
    if any(
        path.is_absolute() or ".." in path.parts or not path.parts
        for path in initialized
    ):
        raise ValueError("Worktree 初始化路径元数据无效。")

    def known(relative: Path) -> bool:
        text = relative.as_posix()
        if text in tracked:
            return True
        if any(prefix == relative or prefix in relative.parents for prefix in initialized):
            return True
        return any(
            text == gitlink or text.startswith(f"{gitlink}/") for gitlink in gitlinks
        )

    unknown: list[str] = []
    for current, directories, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        relative_current = current_path.relative_to(root)
        if relative_current == Path("."):
            files = [name for name in files if name != ".git"]
        retained_directories: list[str] = []
        for name in directories:
            candidate = current_path / name
            relative = candidate.relative_to(root)
            if candidate.is_symlink() or any(
                relative.as_posix() == gitlink for gitlink in gitlinks
            ):
                if not known(relative):
                    unknown.append(relative.as_posix())
            else:
                retained_directories.append(name)
        directories[:] = retained_directories
        for name in files:
            relative = (current_path / name).relative_to(root)
            if not known(relative):
                unknown.append(relative.as_posix())
    return tuple(sorted(set(unknown)))


def _read_index_paths(
    index_path: Path,
    common_git_dir: Path,
) -> tuple[frozenset[str], frozenset[str]]:
    try:
        data = index_path.read_bytes()
        if len(data) < 12 or data[:4] != b"DIRC":
            raise ValueError("Git index 头无效。")
        version = int.from_bytes(data[4:8], "big")
        if version not in {2, 3}:
            raise ValueError(f"不支持快速恢复 Git index v{version}。")
        count = int.from_bytes(data[8:12], "big")
        config_text = (common_git_dir / "config").read_text(
            encoding="utf-8", errors="replace"
        )
        oid_bytes = 32 if re.search(
            r"(?im)^\s*objectformat\s*=\s*sha256\s*$", config_text
        ) else 20
        fixed_size = 40 + oid_bytes + 2
        offset = 12
        tracked: set[str] = set()
        gitlinks: set[str] = set()
        for _ in range(count):
            start = offset
            if start + fixed_size > len(data):
                raise ValueError("Git index 条目被截断。")
            mode = int.from_bytes(data[start + 24 : start + 28], "big")
            flags_offset = start + 40 + oid_bytes
            flags = int.from_bytes(data[flags_offset : flags_offset + 2], "big")
            path_start = start + fixed_size
            if version == 3 and flags & 0x4000:
                path_start += 2
            terminator = data.find(b"\0", path_start)
            if terminator < 0:
                raise ValueError("Git index 路径未终止。")
            path = data[path_start:terminator].decode("utf-8", errors="surrogateescape")
            tracked.add(path)
            if mode & 0o170000 == 0o160000:
                gitlinks.add(path)
            entry_size = terminator + 1 - start
            offset = start + ((entry_size + 7) // 8) * 8
        return frozenset(tracked), frozenset(gitlinks)
    except OSError as exc:
        raise ValueError(f"无法只读检查 Git index：{exc}") from exc


def _porcelain_counts(
    porcelain: str,
    initialization_paths: tuple[str, ...],
) -> tuple[int, int, int]:
    initialized = tuple(Path(value) for value in initialization_paths)

    def initialized_path(value: str) -> bool:
        candidate = Path(value)
        return any(
            candidate == prefix or prefix in candidate.parents
            for prefix in initialized
        )

    staged = tracked = untracked = 0
    records = porcelain.split("\0")
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if not record:
            continue
        if len(record) < 3:
            raise ValueError("Git porcelain 状态记录无效。")
        x, y = record[0], record[1]
        path = record[3:]
        if x in {"R", "C"} or y in {"R", "C"}:
            index += 1
        if x == "?" and y == "?":
            if not initialized_path(path):
                untracked += 1
            continue
        if x not in {" ", "?"}:
            staged += 1
        if y not in {" ", "?"}:
            tracked += 1
    return tracked, staged, untracked


def _escape_gitignore_path(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace(" ", "\\ ")
    if escaped.startswith(("#", "!")):
        escaped = f"\\{escaped}"
    return escaped
