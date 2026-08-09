from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from artcode.agent import AgentLoop, PlanMemory, RequestPreparer
from artcode.commands import CommandDispatcher, create_default_registry
from artcode.mcp import McpStartupReport
from artcode.permissions import ApprovalChoice, PermissionState
from artcode.permissions.service import PermissionService
from artcode.persistence import MemoryStatusSnapshot, PersistenceStatus
from artcode.prompting.assembler import PromptRequestAssembler
from artcode.runtime import ArtCodeRuntime, RuntimeState
from artcode.tools import AllowedPathPolicy, ToolExecutionContext, create_default_tool_registry
from artcode.tools.execution import ToolExecutionService
from artcode.workspace import Workspace


@dataclass(frozen=True)
class _ApprovalPort:
    tui: object

    async def request_approval(self, request):
        return await self.tui.request_approval(request)

    async def request_mcp_approval(self, preview, plan_mode: bool) -> bool:
        return await self.tui.confirm_mcp_tool(preview, plan_mode)


class _SessionService:
    def __init__(self, status: PersistenceStatus | None = None) -> None:
        self.status = status or PersistenceStatus("test-session", False)

    def sessions_summary(self, limit: int = 20):
        return ()


class _MemoryService:
    def __init__(self, root: Path) -> None:
        self.root = root

    def status_snapshot(self) -> MemoryStatusSnapshot:
        return MemoryStatusSnapshot(
            self.root / "user-memory",
            self.root / "project-memory",
            0,
            0,
            0,
            0,
            0,
            0,
            0,
        )


def build_test_runtime(
    config,
    provider,
    conversation,
    tui,
    *,
    tool_registry=None,
    tool_context=None,
    commands=None,
    plan_memory=None,
    agent_loop=None,
    workspace=None,
    permission_state=None,
    state=None,
    permission_engine=None,
    rule_writer=None,
    context_manager=None,
    request_assembler=None,
    request_preparer=None,
    persistence=None,
):
    selected_workspace = workspace or Workspace.from_path(config.workspace)
    selected_state = state or RuntimeState(permission_state or PermissionState())
    registry = tool_registry or create_default_tool_registry()
    context = tool_context or ToolExecutionContext(
        AllowedPathPolicy((selected_workspace.root,)),
        default_cwd=selected_workspace.root,
        permission_state=selected_state.permission,
    )
    memory = plan_memory or (
        persistence.plan_memory if persistence is not None else PlanMemory()
    )
    preparer = request_preparer or RequestPreparer(
        conversation,
        request_assembler or PromptRequestAssembler(),
        registry,
        context,
        context_manager=context_manager,
        durable_prompt=(
            persistence.prompt_context if persistence is not None else None
        ),
    )
    permission_service = PermissionService(
        selected_state.permission,
        engine=permission_engine,
        approver=_ApprovalPort(tui) if permission_engine is not None else None,
        rule_writer=rule_writer,
    )
    loop = agent_loop or AgentLoop(
        provider=provider,
        conversation=conversation,
        tool_registry=registry,
        tool_context=context,
        plan_memory=memory,
        tool_executor=ToolExecutionService(registry, context, permission_service),
        context_manager=context_manager,
        request_preparer=preparer,
        natural_turn_observer=(
            persistence.memory_service if persistence is not None else None
        ),
        session_id=(
            persistence.status.session_id if persistence is not None else "test-session"
        ),
    )
    sessions = (
        persistence.session_service
        if persistence is not None
        else _SessionService()
    )
    long_memory = (
        persistence.memory_service
        if persistence is not None
        else _MemoryService(selected_workspace.root)
    )
    return ArtCodeRuntime(
        config=config,
        conversation=conversation,
        tui=tui,
        workspace=selected_workspace,
        state=selected_state,
        tool_context=context,
        plan_memory=memory,
        agent_loop=loop,
        command_dispatcher=CommandDispatcher(commands or create_default_registry()),
        session_service=sessions,
        memory_service=long_memory,
        startup_status=selected_state.startup_snapshot(
            config,
            workspace=str(selected_workspace.root),
        ),
        mcp_report=McpStartupReport(),
    )


__all__ = ["build_test_runtime"]
