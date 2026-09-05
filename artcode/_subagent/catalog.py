from __future__ import annotations

import asyncio
from pathlib import Path
import secrets
import time
from typing import Callable

from artcode.core.model import Model, Usage
from artcode.core.subagent import (
    ModelFactory,
    ParentRunSnapshot,
    RoleCatalogSnapshot,
    SubagentKind,
    TaskNotification,
    TaskRequest,
    TaskSnapshot,
    TaskState,
)
from artcode.core.tool import PermissionMode, RunMode, Tool, ToolEffect
from artcode.core.workspace import Workspace

from .execution import execute_task
from .notifications import notification
from .roles import Role, discover_roles, effective_capabilities
from .scheduler import Scheduler
from .tasks import TaskRecord


class LocalSubagents:
    def __init__(
        self,
        project_roles: Path,
        user_roles: Path,
        builtin_roles: Path,
        *,
        workspace: Workspace,
        tools: Tool,
        model_factory: ModelFactory,
        extension_roots: tuple[Path, ...] = (),
        model_tiers: dict[str, str] | None = None,
        background_tools: frozenset[str] | None = None,
        max_concurrency: int = 4,
        foreground_timeout_seconds: float = 120.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if foreground_timeout_seconds <= 0:
            raise ValueError("前台等待时间必须为正数。")
        self.project_roles = project_roles
        self.user_roles = user_roles
        self.builtin_roles = builtin_roles
        self.extension_roots = extension_roots
        self.workspace = workspace
        self.tools = tools
        self.model_factory = model_factory
        self.model_tiers = model_tiers or {}
        base_names = {
            item.name
            for item in tools.open_run(workspace, RunMode.CHAT).descriptors
            if item.subagent_allowed
        }
        self.background_tools = background_tools if background_tools is not None else frozenset(base_names)
        self.scheduler = Scheduler(max_concurrency)
        self.foreground_timeout_seconds = foreground_timeout_seconds
        self.clock = clock
        self._roles: dict[str, Role] = {}
        self._role_snapshot = RoleCatalogSnapshot((), ())
        self._tasks: dict[str, TaskRecord] = {}
        self._notifications: list[TaskNotification] = []
        self._closed = False

    def refresh_roles(self) -> RoleCatalogSnapshot:
        descriptors = self.tools.open_run(self.workspace, RunMode.CHAT).descriptors
        self._roles, self._role_snapshot = discover_roles(
            self.project_roles,
            self.user_roles,
            self.builtin_roles,
            self.extension_roots,
            descriptors,
            self.model_tiers,
        )
        return self._role_snapshot

    def submit(self, request: TaskRequest, parent: ParentRunSnapshot) -> TaskSnapshot:
        if self._closed:
            raise RuntimeError("Subagent 模块已关闭。")
        if not isinstance(request, TaskRequest) or not isinstance(parent, ParentRunSnapshot):
            raise TypeError("request/parent 类型无效。")
        task_id = self._new_id()
        record = TaskRecord(
            task_id,
            request.kind,
            request.task.strip(),
            request.role,
            request.background or request.kind is SubagentKind.FORK,
            self.clock(),
        )
        self._tasks[task_id] = record
        role = self._roles.get(request.role or "") if request.role else None
        if request.kind is SubagentKind.DEFINITION and role is None:
            return self._fail_immediately(record, f"Role 不可用：{request.role}")
        if request.kind is SubagentKind.FORK and request.role and role is None:
            return self._fail_immediately(record, f"Role 不可用：{request.role}")

        parent_names = frozenset(item.name for item in parent.tools.descriptors)
        if role is not None:
            capabilities = effective_capabilities(
                parent_names,
                role.allow,
                role.deny,
                self.background_tools,
            )
            permission_mode = role.permission_mode
            max_rounds = role.max_rounds
            model_name = (
                parent.prompt.model
                if role.model == "inherit"
                else self.model_tiers[role.model]
            )
            needs_worktree = role.isolation == "worktree"
        else:
            capabilities = frozenset(
                parent_names & self.background_tools
                - {"agent", "task_list", "task_get", "task_cancel", "load_skill"}
            )
            permission_mode = parent.tools.permission.mode
            max_rounds = 50
            model_name = parent.prompt.model
            by_name = {item.name: item for item in parent.tools.descriptors}
            needs_worktree = any(
                by_name[name].effect is not ToolEffect.OBSERVE
                for name in capabilities
                if name in by_name
            )
        if needs_worktree:
            try:
                record.worktree_plan = self.workspace.freeze_worktree()
            except Exception as exc:
                return self._fail_immediately(record, str(exc))
        runner = asyncio.create_task(
            self._run_record(
                record,
                parent,
                role,
                capabilities,
                permission_mode,
                max_rounds,
                model_name,
            ),
            name=f"subagent:{task_id}",
        )
        record.runner = runner
        return record.snapshot()

    def list(self) -> tuple[TaskSnapshot, ...]:
        return tuple(record.snapshot() for record in self._tasks.values())

    def get(self, task_id: str) -> TaskSnapshot:
        record = self._tasks.get(task_id)
        if record is None:
            raise ValueError(f"Task 不存在：{task_id}")
        return record.snapshot()

    async def wait(self, task_id: str) -> TaskSnapshot:
        record = self._record(task_id)
        if isinstance(record.runner, asyncio.Task):
            await asyncio.gather(record.runner, return_exceptions=True)
        return record.snapshot()

    async def wait_foreground(self, task_id: str) -> TaskSnapshot:
        record = self._record(task_id)
        if not isinstance(record.runner, asyncio.Task):
            return record.snapshot()
        background_wait = asyncio.create_task(record.background_event.wait())
        try:
            done, _ = await asyncio.wait(
                (record.runner, background_wait),
                timeout=self.foreground_timeout_seconds,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not done:
                record.background = True
                record.background_event.set()
        except asyncio.CancelledError:
            record.background = True
            record.background_event.set()
            raise
        finally:
            background_wait.cancel()
            await asyncio.gather(background_wait, return_exceptions=True)
        return record.snapshot()

    def background(self, task_id: str) -> TaskSnapshot:
        record = self._record(task_id)
        record.background = True
        record.background_event.set()
        return record.snapshot()

    async def cancel(self, task_id: str) -> TaskSnapshot:
        record = self._record(task_id)
        if record.state in {TaskState.COMPLETED, TaskState.FAILED, TaskState.LIMIT, TaskState.CANCELLED}:
            return record.snapshot()
        if isinstance(record.runner, asyncio.Task):
            record.runner.cancel()
            await asyncio.gather(record.runner, return_exceptions=True)
        else:
            record.state = TaskState.CANCELLED
            record.finished_at = self.clock()
            self._notify(record)
        return record.snapshot()

    def take_notifications(self) -> tuple[TaskNotification, ...]:
        result = tuple(self._notifications)
        self._notifications.clear()
        return result

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        running = [
            record.runner
            for record in self._tasks.values()
            if isinstance(record.runner, asyncio.Task) and not record.runner.done()
        ]
        for task in running:
            task.cancel()
        if running:
            await asyncio.gather(*running, return_exceptions=True)

    async def _run_record(
        self,
        record: TaskRecord,
        parent: ParentRunSnapshot,
        role: Role | None,
        capabilities: frozenset[str],
        permission_mode: PermissionMode,
        max_rounds: int,
        model_name: str | None,
    ) -> None:
        try:
            async with self.scheduler.semaphore:
                record.started_at = self.clock()
                model = self.model_factory(model_name)
                await execute_task(
                    record,
                    parent,
                    role,
                    workspace=self.workspace,
                    tools=self.tools,
                    model=model,
                    capabilities=capabilities,
                    permission_mode=permission_mode,
                    max_rounds=max_rounds,
                    model_name=model_name,
                )
        except asyncio.CancelledError:
            record.state = TaskState.CANCELLED
            if not record.result:
                record.result = "Task 已取消。"
        except BaseException as exc:
            record.state = TaskState.FAILED
            record.result = str(exc)
        finally:
            record.finished_at = self.clock()
            self._notify(record)

    def _fail_immediately(self, record: TaskRecord, detail: str) -> TaskSnapshot:
        record.state = TaskState.FAILED
        record.result = detail
        record.finished_at = self.clock()
        self._notify(record)
        return record.snapshot()

    def _notify(self, record: TaskRecord) -> None:
        if record.notified or not record.background:
            return
        record.notified = True
        self._notifications.append(notification(record))

    def _record(self, task_id: str) -> TaskRecord:
        record = self._tasks.get(task_id)
        if record is None:
            raise ValueError(f"Task 不存在：{task_id}")
        return record

    def _new_id(self) -> str:
        while True:
            candidate = f"task-{secrets.token_hex(4)}"
            if candidate not in self._tasks:
                return candidate
