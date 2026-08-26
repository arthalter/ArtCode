from __future__ import annotations

from dataclasses import dataclass
from contextlib import ExitStack
from pathlib import Path
from typing import Mapping

from artcode.agent import AgentLoop, AgentMode, AgentRunRequest, PlanMemory, RequestPreparer
from artcode.context_management import (
    ContextArtifactStore,
    ContextManager,
    ContextSummarizer,
    LightweightCompactor,
)
from artcode.conversation import ConversationContext, ConversationSnapshot
from artcode.permissions import PermissionSnapshot
from artcode.persistence import DurablePaths
from artcode.prompting.durable import DurablePromptSource
from artcode.prompting.assembler import PromptRequestAssembler
from artcode.providers.base import StreamingProvider
from artcode.sandbox import SeatbeltSession
from artcode.tools import ToolEnvironment, ToolRegistry, WorkspacePathPolicy
from artcode.tools.execution import ToolExecutionService
from artcode.workspace import Workspace
from artcode.worktrees import WorktreeManager

from .models import AgentCreateRequest, AgentKind, RoleDefinition
from .permissions import SubagentPermissionService, restrict_permission
from .policy import SubagentCapabilities, compute_capabilities
from .runtime import SubagentRuntime


_SUBAGENT_SYSTEM = (
    "你正在以非交互子 Agent 身份工作。请独立完成任务；不要询问用户，"
    "不要委派其他 Agent。完成后直接给出精简、可交接的结论。"
)


@dataclass(frozen=True)
class SubagentLaunch:
    request: AgentCreateRequest
    role: RoleDefinition | None
    parent_snapshot: ConversationSnapshot
    parent_messages: tuple[dict, ...]
    parent_tool_names: frozenset[str]
    parent_permission: PermissionSnapshot
    capabilities: SubagentCapabilities
    baseline: str | None
    worktree_rules: object | None = None
    baseline_error: str = ""


class SubagentFactory:
    def __init__(
        self,
        *,
        provider: StreamingProvider,
        tool_registry: ToolRegistry,
        base_environment: ToolEnvironment,
        permission_engine,
        context_config,
        worktrees: WorktreeManager,
        model_tiers: Mapping[str, str],
        background_tools: frozenset[str],
        durable_paths: DurablePaths | None = None,
    ) -> None:
        self.provider = provider
        self.tool_registry = tool_registry
        self.base_environment = base_environment
        self.permission_engine = permission_engine
        self.context_config = context_config
        self.worktrees = worktrees
        self.model_tiers = dict(model_tiers)
        self.background_tools = frozenset(background_tools)
        self.durable_paths = durable_paths

    def prepare_launch(
        self,
        request: AgentCreateRequest,
        *,
        role: RoleDefinition | None,
        parent_snapshot: ConversationSnapshot,
        parent_permission: PermissionSnapshot,
        parent_policy,
        parent_messages: tuple[dict, ...] = (),
        parent_tool_names: frozenset[str] | None = None,
    ) -> SubagentLaunch:
        if request.kind is AgentKind.DEFINITION and role is None:
            raise ValueError("定义式子 Agent 缺少角色快照。")
        caps = compute_capabilities(
            parent_policy,
            self.tool_registry.descriptors(),
            role,
            self.background_tools,
            parent_tool_names,
        )
        baseline: str | None = None
        rules = None
        error = ""
        if caps.requires_worktree:
            try:
                baseline = self.worktrees.capture_baseline()
                rules = self.worktrees.capture_initialization_rules()
            except Exception as exc:
                error = str(exc)
        return SubagentLaunch(
            request,
            role,
            parent_snapshot,
            tuple(parent_messages),
            frozenset(parent_tool_names or ()),
            parent_permission,
            caps,
            baseline,
            rules,
            error,
        )

    async def create(self, task_id: str, launch: SubagentLaunch) -> SubagentRuntime:
        if launch.baseline_error:
            raise RuntimeError(f"无法为需要写入的子 Agent 冻结 Git 基准：{launch.baseline_error}")
        lease = None
        workspace = Workspace.from_path(self.base_environment.path_policy.workspace.root)
        if launch.capabilities.requires_worktree:
            if launch.baseline is None:
                raise RuntimeError("需要 Worktree 的子 Agent 缺少冻结的 Git 基准。")
            lease = self.worktrees.acquire(task_id, launch.baseline, rules=launch.worktree_rules)
            workspace = Workspace.from_path(lease.path)
        resources = ExitStack()
        try:
            return await self._build_runtime(
                task_id, launch, workspace, lease, resources
            )
        except BaseException:
            try:
                resources.close()
            finally:
                if lease is not None:
                    self.worktrees.handoff(lease)
            raise

    async def _build_runtime(
        self,
        task_id: str,
        launch: SubagentLaunch,
        workspace: Workspace,
        lease,
        resources: ExitStack,
    ) -> SubagentRuntime:
        sensitive = () if lease is not None else (workspace.worktrees_root,)
        readonly_paths = tuple(
            child.resolve()
            for child in workspace.root.iterdir()
            if child.is_symlink() and child.exists() and child.is_dir()
        )
        seatbelt = None
        if self.base_environment.seatbelt is not None:
            git_readable: tuple[Path, ...] = ()
            git_writable: tuple[Path, ...] = ()
            if lease is not None:
                common_git = (lease.main_workspace / ".git").resolve(strict=True)
                pointer = (lease.path / ".git").read_text(encoding="utf-8")
                linked_literal = Path(pointer.removeprefix("gitdir: ").strip())
                if not linked_literal.is_absolute():
                    linked_literal = lease.path / linked_literal
                linked_git = linked_literal.resolve(strict=True)
                branch_ref = common_git / "refs" / "heads" / lease.branch
                branch_log = common_git / "logs" / "refs" / "heads" / lease.branch
                git_readable = (common_git,)
                git_writable = (
                    common_git / "objects",
                    linked_git,
                    branch_ref,
                    Path(f"{branch_ref}.lock"),
                    branch_log,
                    Path(f"{branch_log}.lock"),
                    common_git / "packed-refs",
                    common_git / "packed-refs.lock",
                )
            seatbelt = SeatbeltSession(
                workspace.root,
                sensitive,
                isolation_root=None if lease is None else lease.main_workspace,
                readable_paths=(*readonly_paths, *git_readable),
                writable_paths=git_writable,
            )
            resources.callback(seatbelt.close)
            await seatbelt.start()
        environment = ToolEnvironment(
            path_policy=WorkspacePathPolicy(
                workspace, sensitive_paths=sensitive, readonly_paths=readonly_paths
            ),
            command_timeout_seconds=self.base_environment.command_timeout_seconds,
            default_cwd=workspace.root,
            seatbelt=seatbelt,
            artifact_store=None,
            agent_id=task_id,
            is_subagent=True,
        )
        if launch.request.kind is AgentKind.FORK:
            conversation = (
                ConversationContext.from_messages(launch.parent_messages)
                if launch.parent_messages
                else ConversationContext.from_snapshot(launch.parent_snapshot)
            )
        else:
            conversation = ConversationContext(
                system_prompt=self._definition_system_prompt(workspace)
            )
        conversation.append_system(_SUBAGENT_SYSTEM, mode="subagent")
        if launch.role is not None:
            conversation.append_system(launch.role.system_prompt, mode="subagent")
        if lease is not None:
            conversation.append_system(
                f"当前隔离 Worktree：{lease.path}；不得访问主工作区或其他 Worktree。",
                mode="subagent",
            )
        permission_state = restrict_permission(launch.parent_permission, launch.role)
        permissions = SubagentPermissionService(
            task_id, permission_state, engine=self.permission_engine
        )
        artifact_store = ContextArtifactStore(workspace, session_id=task_id)
        resources.callback(artifact_store.close)
        artifact_store.start()
        from artcode.tools.file_cache import FileReadCache

        environment = ToolEnvironment(
            path_policy=environment.path_policy,
            command_timeout_seconds=environment.command_timeout_seconds,
            default_cwd=environment.default_cwd,
            seatbelt=environment.seatbelt,
            artifact_store=artifact_store,
            file_cache=FileReadCache(),
            agent_id=environment.agent_id,
            is_subagent=True,
        )
        context = ContextManager(
            self.context_config,
            ContextSummarizer(self.provider, conversation),
            lightweight_compactor=LightweightCompactor(artifact_store),
        )
        preparer = RequestPreparer(
            conversation,
            PromptRequestAssembler(),
            self.tool_registry,
            environment,
            permission_state,
            context_manager=context,
            preserve_initial_prefix=launch.request.kind is AgentKind.FORK,
        )
        mode = AgentMode("subagent", launch.capabilities.policy, "非交互子 Agent。")
        loop = AgentLoop(
            self.provider,
            conversation,
            self.tool_registry,
            environment,
            plan_memory=PlanMemory(),
            tool_executor=ToolExecutionService(
                self.tool_registry, environment, permissions
            ),
            request_preparer=preparer,
            context_manager=context,
            session_id=task_id,
        )
        owned_resources = resources.pop_all()
        runtime = SubagentRuntime(
            task_id,
            launch.request,
            launch.role,
            conversation,
            environment,
            loop,
            permissions,
            (
                None
                if launch.role is None or launch.role.model_tier == "inherit"
                else self.model_tiers[launch.role.model_tier]
            ),
            lease,
            owned_resources.close,
        )
        runtime._mode = mode  # type: ignore[attr-defined]
        runtime._worktree_manager = self.worktrees  # type: ignore[attr-defined]
        runtime._request_preparer = preparer  # type: ignore[attr-defined]
        return runtime

    def run_request(self, runtime: SubagentRuntime) -> AgentRunRequest:
        return AgentRunRequest(
            user_content=runtime.request.task,
            mode=runtime._mode,  # type: ignore[attr-defined]
            max_iterations=50 if runtime.role is None else runtime.role.max_rounds,
            model_override=runtime.model_override,
        )

    def _definition_system_prompt(self, workspace: Workspace) -> str:
        if self.durable_paths is None:
            from artcode.prompts import SYSTEM_PROMPT

            return SYSTEM_PROMPT
        paths = DurablePaths(
            user_instruction=self.durable_paths.user_instruction,
            project_instruction=workspace.project_instruction_file,
            local_instruction=workspace.local_instruction_file,
            sessions_dir=workspace.sessions_dir,
            user_memory_dir=self.durable_paths.user_memory_dir,
            project_memory_dir=workspace.project_memory_dir,
        )
        return DurablePromptSource(paths).build_system_prompt()
