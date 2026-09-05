from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from artcode._agent import AgentRunner
from artcode._session import LocalSession
from artcode.core.agent import RunFinished, StopReason, ToolBatchEvent
from artcode.core.model import Model
from artcode.core.session import RunContribution, SessionSelection
from artcode.core.subagent import ParentRunSnapshot, TaskState
from artcode.core.tool import PermissionMode, PermissionSnapshot, RunMode, ShellPolicy, Tool, ToolSource
from artcode.core.workspace import Workspace, WorktreeLease

from .roles import Role
from .tasks import TaskRecord


async def execute_task(
    record: TaskRecord,
    parent: ParentRunSnapshot,
    role: Role | None,
    *,
    workspace: Workspace,
    tools: Tool,
    model: Model,
    capabilities: frozenset[str],
    permission_mode: PermissionMode,
    max_rounds: int,
    model_name: str | None,
) -> None:
    lease: WorktreeLease | None = None
    child_workspace = workspace
    child_scope = None
    record.state = TaskState.RUNNING
    if record.worktree_plan is not None:
        lease = workspace.acquire_worktree(record.id, record.worktree_plan)
        child_scope = workspace.open_worktree(lease)
        child_workspace = child_scope
    try:
        with TemporaryDirectory(prefix="artcode-subagent-") as raw:
            session = LocalSession(
                child_workspace.root,
                SessionSelection.new(),
                storage_root=Path(raw),
            )
            try:
                run_tools = tools.open_run(
                    child_workspace,
                    RunMode.CHAT,
                    source=ToolSource.SUBAGENT,
                    allowed_tools=capabilities,
                )
                parent_mode = parent.tools.permission.mode
                rank = {PermissionMode.DEFAULT: 0, PermissionMode.EDIT: 1, PermissionMode.FULL: 2}
                effective = permission_mode if rank[permission_mode] <= rank[parent_mode] else parent_mode
                run_tools = replace(
                    run_tools,
                    permission=PermissionSnapshot(
                        effective,
                        parent.tools.permission.shell_policy,
                        parent.tools.permission.rules,
                    ),
                )
                contributions = (
                    (RunContribution(role.name, role.sop, model_name),) if role is not None else ()
                )
                frozen_prompt = parent.prompt if record.kind.value == "fork" else None
                prepared = await session.prepare_run(
                    record.task,
                    run_tools,
                    contributions=contributions,
                    frozen_prompt=frozen_prompt,
                )
                events = [
                    event
                    async for event in AgentRunner(model, tools, session).run(
                        session.dispatch_run(prepared), max_rounds=max_rounds
                    )
                ]
                finished = next(event for event in reversed(events) if isinstance(event, RunFinished))
                record.rounds = finished.outcome.rounds
                record.usage = finished.outcome.usage
                record.result = finished.outcome.final_text or finished.outcome.detail
                for event in events:
                    if isinstance(event, ToolBatchEvent):
                        record.permission_events.extend(
                            f"{result.tool_name}:{result.error_code}"
                            for result in event.results
                            if result.error_code in {"permission_denied", "permission_required"}
                        )
                record.state = {
                    StopReason.NATURAL: TaskState.COMPLETED,
                    StopReason.LENGTH: TaskState.COMPLETED,
                    StopReason.LIMIT: TaskState.LIMIT,
                    StopReason.CANCELLED: TaskState.CANCELLED,
                }.get(finished.outcome.stop_reason, TaskState.FAILED)
            finally:
                session.close()
    finally:
        if child_scope is not None:
            child_scope.close()
        if lease is not None:
            record.handoff = workspace.release_worktree(lease)
