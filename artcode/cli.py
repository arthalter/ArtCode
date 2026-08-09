from __future__ import annotations

import asyncio
import argparse
from pathlib import Path

from .config import load_config
from .errors import ConfigError
from .providers import OpenAICompatibleProvider
from .runtime import ArtCodeRuntime
from .tools import ToolExecutionContext, create_default_tool_registry
from .tools import WorkspacePathPolicy
from .tui import PromptToolkitTui, TuiRenderer
from .workspace import ArtCodePaths, Workspace, WorkspaceError
from .permissions import PermissionEngine, PermissionState, RuleLoader, RulePaths, RuleWriter
from .security import DangerousCommandValidator
from .sandbox import SeatbeltError, SeatbeltSession
from .mcp import McpManager, load_mcp_configuration
from .context_management import ContextArtifactStore, ContextManager, ContextSummarizer, LightweightCompactor
from .agent import NORMAL_AGENT_MODE, RequestPreparer
from .persistence import PersistenceCoordinator, SessionError, SessionSelection
from .prompting.assembler import PromptRequestAssembler
from importlib.resources import files


async def run_app(
    config_path: Path | None = None,
    workspace_path: Path | None = None,
    artcode_home: Path | None = None,
    *,
    new_session: bool = False,
    resume_session: str | None = None,
) -> int:
    renderer = TuiRenderer()
    artifact_store = None
    seatbelt = None
    persistence = None
    mcp_manager = None
    try:
        app_paths = ArtCodePaths.create(artcode_home)
        workspace = Workspace.from_path(workspace_path)
        config = load_config(config_path or app_paths.config_file)
        provider = OpenAICompatibleProvider(config)
        selection = (
            SessionSelection.new()
            if new_session
            else SessionSelection.resume(resume_session)
            if resume_session is not None
            else SessionSelection.latest()
        )
        persistence = PersistenceCoordinator.start(
            app_paths,
            workspace,
            provider,
            selection,
            secrets=(config.api_key,),
        )
        artifact_store = ContextArtifactStore(workspace)
        artifact_store.start()
        rule_paths = RulePaths.from_context(app_paths, workspace)
        rules = RuleLoader(rule_paths)
        rules.validate_all()
        dangerous = DangerousCommandValidator.load()
        sensitive_paths = (
            app_paths.config_file,
            app_paths.user_permissions_file,
            app_paths.skills_dir,
            workspace.project_permissions_file,
            workspace.local_permissions_file,
            persistence.paths.user_instruction,
            persistence.paths.project_instruction,
            persistence.paths.local_instruction,
            persistence.paths.sessions_dir,
            persistence.paths.user_memory_dir,
            persistence.paths.project_memory_dir,
            Path(str(files("artcode.security").joinpath("dangerous_commands.yml"))),
            Path(str(files("artcode.sandbox").joinpath("seatbelt.sb"))),
        )
        seatbelt = SeatbeltSession(workspace.root, sensitive_paths)
        await seatbelt.start()
    except (ConfigError, WorkspaceError, SessionError, ValueError, SeatbeltError, OSError, RuntimeError) as exc:
        if persistence is not None:
            await persistence.close()
        if artifact_store is not None:
            artifact_store.close()
        if seatbelt is not None:
            seatbelt.close()
        if not isinstance(exc, ConfigError):
            exc = ConfigError(str(exc))
        renderer.show_startup_error(exc)
        return 2

    try:
        tui = PromptToolkitTui(renderer=renderer)
        user_mcp_raw = {"mcp_servers": config.mcp_servers_raw or {}}
        mcp_configs, mcp_issues = load_mcp_configuration(user_mcp_raw, workspace.root)
        mcp_manager = McpManager(
            mcp_configs,
            workspace.root,
            mcp_issues,
            approver=tui.confirm_mcp_server,
        )
        mcp_report = await mcp_manager.start()
        state = PermissionState()
        path_policy = WorkspacePathPolicy(workspace, sensitive_paths)
        tool_context = ToolExecutionContext(
            path_policy,
            default_cwd=workspace.root,
            shell_policy=state.shell_policy,
            seatbelt=seatbelt,
            permission_state=state,
            artifact_store=artifact_store,
        )
        registry = create_default_tool_registry()
        mcp_manager.register_into(registry)
        mcp_report = mcp_manager.report
        conversation = persistence.conversation
        context_manager = ContextManager(
            config.context,
            ContextSummarizer(provider, conversation),
            lightweight_compactor=LightweightCompactor(artifact_store),
        )
        request_assembler = PromptRequestAssembler()
        request_preparer = RequestPreparer(
            conversation,
            request_assembler,
            registry,
            tool_context,
            context_manager=context_manager,
            durable_prompt=persistence.prompt_context,
        )
        await persistence.prepare_restored_context(
            context_manager,
            request_preparer,
            NORMAL_AGENT_MODE,
        )
        runtime = ArtCodeRuntime(
            config=config,
            provider=provider,
            conversation=conversation,
            tui=tui,
            tool_registry=registry,
            tool_context=tool_context,
            workspace=workspace,
            permission_state=state,
            permission_engine=PermissionEngine(rules, dangerous),
            rule_writer=RuleWriter(rules),
            context_manager=context_manager,
            plan_memory=persistence.plan_memory,
            request_assembler=request_assembler,
            request_preparer=request_preparer,
            persistence=persistence,
        )
        renderer.show_mcp_startup(mcp_report)
        return await runtime.run()
    except (ConfigError, ValueError, OSError, RuntimeError) as exc:
        if not isinstance(exc, ConfigError):
            exc = ConfigError(str(exc))
        renderer.show_startup_error(exc)
        return 2
    finally:
        await persistence.close()
        if mcp_manager is not None:
            await mcp_manager.close()
        artifact_store.close()
        seatbelt.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="artcode")
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--config", type=Path)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--new", action="store_true", dest="new_session", help="始终创建新会话")
    selection.add_argument("--resume", metavar="SESSION_ID", help="精确恢复指定会话")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return asyncio.run(
            run_app(
                config_path=args.config,
                workspace_path=args.workspace,
                new_session=args.new_session,
                resume_session=args.resume,
            )
        )
    except KeyboardInterrupt:
        TuiRenderer().show_exit()
        return 130
