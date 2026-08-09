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
from artcode.tools import ToolEnvironment, create_default_tool_registry
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


_WORKSPACES: dict[int, Path] = {}


def register_test_workspace(config, root: Path):
    _WORKSPACES[id(config)] = root
    return config


def build_test_runtime(
    config,
    provider,
    conversation,
    tui,
    *,
    tool_registry=None,
    tool_environment=None,
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
    session_service=None,
    memory_service=None,
    durable_prompt=None,
):
    selected_workspace = workspace or Workspace.from_path(_WORKSPACES[id(config)])
    selected_state = state or RuntimeState(permission_state or PermissionState())
    registry = tool_registry or create_default_tool_registry()
    environment = tool_environment or ToolEnvironment.from_workspace(selected_workspace)
    memory = plan_memory or PlanMemory()
    preparer = request_preparer or RequestPreparer(
        conversation,
        request_assembler or PromptRequestAssembler(),
        registry,
        environment,
        selected_state.permission,
        context_manager=context_manager,
        durable_prompt=durable_prompt,
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
        tool_environment=environment,
        plan_memory=memory,
        tool_executor=ToolExecutionService(registry, environment, permission_service),
        context_manager=context_manager,
        request_preparer=preparer,
        natural_turn_observer=memory_service,
        session_id=(session_service.status.session_id if session_service else "test-session"),
    )
    sessions = session_service or _SessionService()
    long_memory = memory_service or _MemoryService(selected_workspace.root)
    return ArtCodeRuntime(
        config=config,
        conversation=conversation,
        tui=tui,
        workspace=selected_workspace,
        state=selected_state,
        tool_environment=environment,
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


__all__ = ["build_test_runtime", "register_test_workspace"]
