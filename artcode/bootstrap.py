from __future__ import annotations

from contextlib import AsyncExitStack
from dataclasses import dataclass, replace
from importlib.resources import files
from pathlib import Path

from artcode.agent import AgentLoop, NORMAL_AGENT_MODE, RequestPreparer
from artcode.commands import CommandDispatcher, create_default_registry
from artcode.config import ArtCodeConfig, load_config
from artcode.context_management import (
    CompressionTrigger,
    ContextArtifactStore,
    ContextManager,
    ContextSummarizer,
    LightweightCompactor,
)
from artcode.mcp import McpManager, McpStartupReport, load_mcp_configuration
from artcode.permissions import (
    ApprovalChoice,
    ApprovalRequest,
    PermissionEngine,
    PermissionState,
    RuleLoader,
    RulePaths,
    RuleWriter,
)
from artcode.permissions.service import PermissionService
from artcode.persistence import (
    DurablePaths,
    MemoryService,
    SessionSelection,
    SessionService,
)
from artcode.prompting.assembler import PromptRequestAssembler
from artcode.prompting.durable import DurablePromptSource
from artcode.providers import DeepSeekChatProvider
from artcode.runtime import ArtCodeRuntime, RuntimeState
from artcode.sandbox import SeatbeltSession
from artcode.security import DangerousCommandValidator
from artcode.tools import ToolEnvironment, ToolPreview
from artcode.tools import create_default_tool_registry
from artcode.tools.execution import ToolExecutionService
from artcode.tui import PromptToolkitTui, TuiRenderer
from artcode.workspace import ArtCodePaths, Workspace


@dataclass(frozen=True)
class AppOptions:
    config_path: Path | None
    workspace_path: Path | None
    artcode_home: Path | None
    session_selection: SessionSelection


@dataclass(frozen=True)
class BootstrappedApplication:
    runtime: ArtCodeRuntime
    tui: PromptToolkitTui
    mcp_report: McpStartupReport


@dataclass(frozen=True)
class _TuiApprovalPort:
    tui: PromptToolkitTui

    async def request_approval(self, request: ApprovalRequest) -> ApprovalChoice:
        return await self.tui.request_approval(request)

    async def request_mcp_approval(
        self,
        preview: ToolPreview,
        plan_mode: bool,
    ) -> bool:
        return await self.tui.confirm_mcp_tool(preview, plan_mode)


class Bootstrap:
    """The only production composition root and resource owner."""

    def __init__(self, options: AppOptions) -> None:
        self.options = options

    async def run(self) -> int:
        async with AsyncExitStack() as resources:
            application = await self.build(resources)
            return await application.runtime.run()

    async def build(self, resources: AsyncExitStack) -> BootstrappedApplication:
        app_paths = ArtCodePaths.create(self.options.artcode_home)
        workspace = Workspace.from_path(self.options.workspace_path)
        durable_paths = DurablePaths.from_context(app_paths, workspace)
        config = load_config(self.options.config_path or app_paths.config_file)

        provider = DeepSeekChatProvider(config)
        resources.push_async_callback(provider.close)

        session_service = SessionService(durable_paths)
        resources.callback(session_service.close)
        session = session_service.start(self.options.session_selection)

        artifact_store = ContextArtifactStore(
            workspace,
            session_id=session.status.session_id,
        )
        resources.callback(artifact_store.close)
        artifact_store.start()

        rule_loader = RuleLoader(RulePaths.from_context(app_paths, workspace))
        rule_loader.validate_all()
        sensitive_paths = _sensitive_paths(
            app_paths,
            workspace,
            durable_paths,
        )
        seatbelt = SeatbeltSession(workspace.root, sensitive_paths)
        resources.callback(seatbelt.close)
        await seatbelt.start()

        renderer = TuiRenderer()
        tui = PromptToolkitTui(renderer=renderer)
        mcp_configs, mcp_issues = load_mcp_configuration(
            {"mcp_servers": config.mcp_servers_raw},
            workspace.root,
        )
        mcp_manager = McpManager(
            mcp_configs,
            workspace.root,
            mcp_issues,
            approver=tui.confirm_mcp_server,
        )
        resources.push_async_callback(mcp_manager.close)
        await mcp_manager.start()

        memory_service = MemoryService(
            durable_paths,
            provider,
            secrets=(config.api_key,),
        )
        resources.push_async_callback(memory_service.close)

        state = RuntimeState(PermissionState())
        tool_environment = ToolEnvironment.from_workspace(
            workspace,
            sensitive_paths=sensitive_paths,
            seatbelt=seatbelt,
            artifact_store=artifact_store,
        )
        tool_registry = create_default_tool_registry()
        mcp_manager.register_into(tool_registry)

        context_manager = ContextManager(
            config.context,
            ContextSummarizer(provider, session.conversation),
            lightweight_compactor=LightweightCompactor(artifact_store),
        )
        prompt_source = DurablePromptSource(durable_paths)
        request_preparer = RequestPreparer(
            session.conversation,
            PromptRequestAssembler(),
            tool_registry,
            tool_environment,
            state.permission,
            context_manager=context_manager,
            durable_prompt=prompt_source,
        )
        await _prepare_restored_context(
            session_service,
            context_manager,
            request_preparer,
        )

        approval_port = _TuiApprovalPort(tui)
        permission_service = PermissionService(
            state.permission,
            engine=PermissionEngine(
                rule_loader,
                DangerousCommandValidator.load(),
            ),
            approver=approval_port,
            rule_writer=RuleWriter(rule_loader),
        )
        tool_executor = ToolExecutionService(
            tool_registry,
            tool_environment,
            permission_service,
        )
        agent_loop = AgentLoop(
            provider=provider,
            conversation=session.conversation,
            tool_registry=tool_registry,
            tool_environment=tool_environment,
            plan_memory=session.plan_memory,
            tool_executor=tool_executor,
            context_manager=context_manager,
            request_preparer=request_preparer,
            natural_turn_observer=memory_service,
            session_id=session.status.session_id,
        )
        startup_status = _startup_status(
            config,
            workspace,
            state,
            seatbelt,
            session_service,
            prompt_source,
            memory_service,
        )
        runtime = ArtCodeRuntime(
            config=config,
            conversation=session.conversation,
            tui=tui,
            workspace=workspace,
            state=state,
            tool_environment=tool_environment,
            plan_memory=session.plan_memory,
            agent_loop=agent_loop,
            command_dispatcher=CommandDispatcher(create_default_registry()),
            session_service=session_service,
            memory_service=memory_service,
            startup_status=startup_status,
            mcp_report=mcp_manager.report,
        )
        memory_service.add_callback(runtime.show_memory_report)
        return BootstrappedApplication(runtime, tui, mcp_manager.report)


async def _prepare_restored_context(
    sessions: SessionService,
    context_manager: ContextManager,
    preparer: RequestPreparer,
) -> None:
    session = sessions.context
    if session.status.restored and session.status.recovered_messages:
        context_manager.run_lightweight(session.conversation)
        request = preparer.preview_request(NORMAL_AGENT_MODE, include_tools=True)
        estimated = context_manager.estimate_request(request)
        if estimated >= context_manager.config.automatic_threshold:
            await context_manager.compact(
                session.conversation,
                CompressionTrigger.RESTORE,
            )
    if session.resume_reminder_required:
        preparer.require_resume_reminder()


def _startup_status(
    config: ArtCodeConfig,
    workspace: Workspace,
    state: RuntimeState,
    seatbelt: SeatbeltSession,
    sessions: SessionService,
    prompt_source: DurablePromptSource,
    memory: MemoryService,
):
    session = sessions.status
    return replace(
        state.startup_snapshot(
            config,
            workspace=str(workspace.root),
            seatbelt_status=(
                "self-test passed" if seatbelt.self_tested else "initialized"
            ),
        ),
        session_id=session.session_id,
        session_state=(
            "restored"
            if session.restored
            else "new (latest locked)"
            if session.default_locked_new_session
            else "new"
        ),
        recovered_messages=session.recovered_messages,
        bad_session_lines=session.bad_line_count,
        session_truncated=session.truncated,
        instruction_bytes=prompt_source.instructions.total_bytes,
        instruction_issues=len(prompt_source.instructions.issues),
        user_active_notes=memory.user_index_report.active_count,
        project_active_notes=memory.project_index_report.active_count,
    )


def _sensitive_paths(
    app_paths: ArtCodePaths,
    workspace: Workspace,
    durable_paths: DurablePaths,
) -> tuple[Path, ...]:
    return (
        app_paths.config_file,
        app_paths.user_permissions_file,
        app_paths.skills_dir,
        workspace.project_permissions_file,
        workspace.local_permissions_file,
        durable_paths.user_instruction,
        durable_paths.project_instruction,
        durable_paths.local_instruction,
        durable_paths.sessions_dir,
        durable_paths.user_memory_dir,
        durable_paths.project_memory_dir,
        Path(str(files("artcode.security").joinpath("dangerous_commands.yml"))),
        Path(str(files("artcode.sandbox").joinpath("seatbelt.sb"))),
    )


async def run_application(options: AppOptions) -> int:
    return await Bootstrap(options).run()


__all__ = [
    "AppOptions",
    "Bootstrap",
    "BootstrappedApplication",
    "run_application",
]
