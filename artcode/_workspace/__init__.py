"""Local adapter for the public Workspace Interface."""

from __future__ import annotations

import os
from pathlib import Path
import time
from typing import Callable

from artcode.core.workspace import (
    DiscardConfirmation,
    FileChange,
    FileList,
    IsolationMode,
    ProcessOutcome,
    ProcessRequest,
    SearchResult,
    StoredResult,
    TargetSnapshot,
    TextMatch,
    TextSlice,
    WorktreeHandoff,
    WorktreeLease,
    WorktreePlan,
)

from .files import atomic_write, read_utf8, slice_text
from .paths import PathGuard
from .processes import ProcessSupervisor
from .results import ResultStore
from .seatbelt import Seatbelt
from .worktrees import WorktreeManager


class LocalWorkspace:
    """Filesystem-backed adapter bound to one immutable root directory."""

    def __init__(
        self,
        root: Path,
        *,
        sensitive_paths: tuple[Path, ...] = (),
        read_char_limit: int = 20_000,
        result_preview_bytes: int = 4_096,
        result_read_char_limit: int = 20_000,
        process_output_limit: int = 20_000,
        sandbox_exec: Path = Path("/usr/bin/sandbox-exec"),
        clock: Callable[[], float] = time.time,
        isolation_root: Path | None = None,
        readable_paths: tuple[Path, ...] = (),
    ) -> None:
        if read_char_limit < 1 or process_output_limit < 1:
            raise ValueError("读取和进程输出限制必须为正整数。")
        self._paths = PathGuard(root, sensitive_paths, readable_paths)
        self._read_char_limit = read_char_limit
        self._result_preview_bytes = result_preview_bytes
        self._result_read_char_limit = result_read_char_limit
        self._process_output_limit = process_output_limit
        self._sandbox_exec = sandbox_exec
        self._results = ResultStore(
            self._paths.root,
            self._paths.scope_id,
            preview_bytes=result_preview_bytes,
            read_char_limit=result_read_char_limit,
        )
        self._processes = ProcessSupervisor()
        self._seatbelt = Seatbelt(
            self._paths.root,
            self._paths.sensitive_paths,
            executable=sandbox_exec,
            isolation_root=isolation_root,
            readable_paths=readable_paths,
        )
        self._worktrees = WorktreeManager(self._paths.root, self._paths.scope_id, clock=clock)
        self._closed = False

    @property
    def root(self) -> Path:
        return self._paths.root

    @property
    def scope_id(self) -> str:
        return self._paths.scope_id

    @property
    def active_process_count(self) -> int:
        return self._processes.active_count

    def prepare_target(self, path: str | Path, *, must_exist: bool) -> TargetSnapshot:
        self._ensure_open()
        return self._paths.prepare(path, must_exist=must_exist)

    def read_text(
        self,
        target: TargetSnapshot,
        *,
        start_line: int | None = None,
        end_line: int | None = None,
    ) -> TextSlice:
        self._ensure_open()
        prepared = self._paths.verify(target)
        content = read_utf8(self.root, prepared)
        return slice_text(
            content,
            start_line=start_line,
            end_line=end_line,
            char_limit=self._read_char_limit,
        )

    def write_text(
        self,
        target: TargetSnapshot,
        content: str,
        *,
        overwrite: bool,
    ) -> FileChange:
        self._ensure_open()
        if not isinstance(content, str):
            raise TypeError("content 必须是字符串。")
        prepared = self._paths.verify(target)
        self._paths.ensure_writable(prepared)
        return atomic_write(self.root, prepared, content, overwrite=overwrite)

    def edit_text(self, target: TargetSnapshot, old_text: str, new_text: str) -> FileChange:
        self._ensure_open()
        if not isinstance(old_text, str) or not old_text:
            raise ValueError("old_text 必须是非空字符串。")
        if not isinstance(new_text, str):
            raise TypeError("new_text 必须是字符串。")
        prepared = self._paths.verify(target)
        self._paths.ensure_writable(prepared)
        content = read_utf8(self.root, prepared)
        if content.count(old_text) != 1:
            raise ValueError("old_text 必须在目标文件中唯一匹配。")
        return atomic_write(self.root, prepared, content.replace(old_text, new_text, 1), overwrite=True)

    def find_files(self, pattern: str, *, limit: int = 1000) -> FileList:
        self._ensure_open()
        _validate_discovery(pattern, limit)
        selected: list[str] = []
        for candidate in self.root.glob(pattern):
            try:
                resolved = self._paths.ensure_discoverable(candidate)
            except (OSError, ValueError):
                continue
            if resolved.is_file():
                selected.append(self._paths.relative(resolved))
        ordered = sorted(set(selected))
        return FileList(tuple(ordered[:limit]), truncated=len(ordered) > limit)

    def search_text(
        self,
        query: str,
        *,
        glob: str = "**/*",
        limit: int = 1000,
    ) -> SearchResult:
        self._ensure_open()
        if not isinstance(query, str) or not query:
            raise ValueError("搜索文本不能为空。")
        _validate_discovery(glob, limit)
        matches: list[TextMatch] = []
        skipped = 0
        truncated = False
        candidates: list[tuple[str, Path]] = []
        for candidate in self.root.glob(glob):
            try:
                resolved = self._paths.ensure_discoverable(candidate)
            except (OSError, ValueError):
                continue
            if resolved.is_file():
                candidates.append((self._paths.relative(resolved), resolved))
        for relative, path in sorted(set(candidates)):
            try:
                prepared = self._paths.prepare(relative, must_exist=True)
                content = read_utf8(self.root, prepared)
            except (UnicodeDecodeError, OSError):
                skipped += 1
                continue
            for line_number, line in enumerate(content.splitlines(), 1):
                if query in line:
                    if len(matches) == limit:
                        truncated = True
                        break
                    matches.append(TextMatch(relative, line_number, line))
            if truncated:
                break
        return SearchResult(tuple(matches), truncated, skipped)

    def store_result(self, source: str, content: str) -> StoredResult:
        self._ensure_open()
        if not isinstance(source, str) or not source:
            raise ValueError("结果来源不能为空。")
        if not isinstance(content, str):
            raise TypeError("结果内容必须是字符串。")
        return self._results.store(source, content)

    def read_result(
        self,
        reference: str,
        *,
        start_line: int | None = None,
        end_line: int | None = None,
    ) -> TextSlice:
        self._ensure_open()
        return self._results.read(reference, start_line=start_line, end_line=end_line)

    async def run_process(self, request: ProcessRequest) -> ProcessOutcome:
        self._ensure_open()
        if not isinstance(request, ProcessRequest):
            raise TypeError("request 必须是 ProcessRequest。")
        cwd = self._paths.directory(request.cwd)
        argv = request.argv
        if request.isolation is IsolationMode.ENFORCED:
            argv = (*await self._seatbelt.prefix(), *argv)
        elif request.isolation is not IsolationMode.EXPLICIT_UNSAFE:
            raise ValueError("未知进程隔离模式。")
        inherited = ("PATH", "LANG", "LC_ALL", "TERM", "TMPDIR")
        environment = {key: os.environ[key] for key in inherited if key in os.environ}
        environment.setdefault("PATH", "/usr/bin:/bin:/usr/sbin:/sbin")
        environment["HOME"] = str(Path.home())
        for key, value in request.environment:
            if not isinstance(key, str) or not key or not isinstance(value, str):
                raise ValueError("进程环境变量必须是非空字符串键值对。")
            environment[key] = value
        raw = await self._processes.run(
            argv,
            cwd=cwd,
            environment=environment,
            timeout_seconds=request.timeout_seconds,
        )
        stdout = raw.stdout.decode("utf-8", errors="replace")
        stderr = raw.stderr.decode("utf-8", errors="replace")
        stdout_ref = stderr_ref = None
        stdout_truncated = len(stdout) > self._process_output_limit
        stderr_truncated = len(stderr) > self._process_output_limit
        if stdout_truncated:
            stdout_ref = self.store_result("process-stdout", stdout).reference
        if stderr_truncated:
            stderr_ref = self.store_result("process-stderr", stderr).reference
        return ProcessOutcome(
            argv=request.argv,
            returncode=raw.returncode,
            stdout=stdout[: self._process_output_limit],
            stderr=stderr[: self._process_output_limit],
            timed_out=raw.timed_out,
            cancelled=raw.cancelled,
            start_error=raw.start_error,
            stdout_truncated=stdout_truncated,
            stderr_truncated=stderr_truncated,
            stdout_reference=stdout_ref,
            stderr_reference=stderr_ref,
        )

    def freeze_worktree(self) -> WorktreePlan:
        self._ensure_open()
        return self._worktrees.freeze()

    def acquire_worktree(
        self, task_id: str, plan: WorktreePlan, *, name: str | None = None
    ) -> WorktreeLease:
        self._ensure_open()
        return self._worktrees.acquire(task_id, plan, name=name)

    def open_worktree(self, lease: WorktreeLease) -> LocalWorkspace:
        self._ensure_open()
        if not self._worktrees.owns(lease):
            raise ValueError("Worktree lease 不属于当前 Workspace。")
        return LocalWorkspace(
            lease.path,
            read_char_limit=self._read_char_limit,
            result_preview_bytes=self._result_preview_bytes,
            result_read_char_limit=self._result_read_char_limit,
            process_output_limit=self._process_output_limit,
            sandbox_exec=self._sandbox_exec,
            isolation_root=self.root,
            readable_paths=lease.readable_paths,
        )

    def inspect_worktree(self, lease: WorktreeLease) -> WorktreeHandoff:
        self._ensure_open()
        return self._worktrees.inspect(lease)

    def release_worktree(self, lease: WorktreeLease) -> WorktreeHandoff:
        self._ensure_open()
        return self._worktrees.release(lease)

    def cleanup_worktrees(
        self, *, active_task_ids: set[str], max_age_seconds: float = 86_400
    ) -> tuple[str, ...]:
        self._ensure_open()
        return self._worktrees.cleanup(active_task_ids, max_age_seconds=max_age_seconds)

    def discard_worktree(
        self, lease: WorktreeLease, confirmation: DiscardConfirmation
    ) -> None:
        self._ensure_open()
        self._worktrees.discard(lease, confirmation)

    def find_worktree(self, task_id: str) -> WorktreeLease | None:
        self._ensure_open()
        return self._worktrees.find(task_id)

    def list_managed_worktrees(self) -> tuple[WorktreeHandoff, ...]:
        self._ensure_open()
        return self._worktrees.list_managed()

    async def aclose(self) -> None:
        if self._closed:
            return
        await self._processes.close()
        self._finish_close()

    def close(self) -> None:
        if self._closed:
            return
        if self._processes.active_count:
            raise RuntimeError("存在活动进程，请使用 await aclose()。")
        self._finish_close()

    def _finish_close(self) -> None:
        self._worktrees.close()
        self._seatbelt.close()
        self._results.close()
        self._closed = True

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("Workspace scope 已关闭。")


def _validate_discovery(pattern: str, limit: int) -> None:
    if not isinstance(pattern, str) or not pattern:
        raise ValueError("文件模式不能为空。")
    if Path(pattern).is_absolute() or ".." in Path(pattern).parts:
        from artcode.core.workspace import PathOutsideWorkspace

        raise PathOutsideWorkspace(f"文件模式不能逃离 Workspace：{pattern}")
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("limit 必须是正整数。")


__all__ = ["LocalWorkspace"]
