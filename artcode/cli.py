from __future__ import annotations

import asyncio
import argparse
from pathlib import Path

from .config import load_config
from .conversation import ConversationContext
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
from importlib.resources import files


async def run_app(
    config_path: Path | None = None,
    workspace_path: Path | None = None,
    artcode_home: Path | None = None,
) -> int:
    renderer = TuiRenderer()
    try:
        app_paths = ArtCodePaths.create(artcode_home)
        workspace = Workspace.from_path(workspace_path)
        config = load_config(config_path or app_paths.config_file)
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
            Path(str(files("artcode.security").joinpath("dangerous_commands.yml"))),
            Path(str(files("artcode.sandbox").joinpath("seatbelt.sb"))),
        )
        seatbelt = SeatbeltSession(workspace.root, sensitive_paths)
        await seatbelt.start()
    except (ConfigError, WorkspaceError, ValueError, SeatbeltError) as exc:
        if not isinstance(exc, ConfigError):
            exc = ConfigError(str(exc))
        renderer.show_startup_error(exc)
        return 2

    provider = OpenAICompatibleProvider(config)
    state = PermissionState()
    path_policy = WorkspacePathPolicy(workspace, sensitive_paths)
    tool_context = ToolExecutionContext(
        path_policy,
        default_cwd=workspace.root,
        shell_policy=state.shell_policy,
        seatbelt=seatbelt,
        permission_state=state,
    )
    runtime = ArtCodeRuntime(
        config=config,
        provider=provider,
        conversation=ConversationContext(),
        tui=PromptToolkitTui(renderer=renderer),
        tool_registry=create_default_tool_registry(),
        tool_context=tool_context,
        workspace=workspace,
        permission_state=state,
        permission_engine=PermissionEngine(rules, dangerous),
        rule_writer=RuleWriter(rules),
    )
    try:
        return await runtime.run()
    finally:
        seatbelt.close()


def main() -> int:
    parser = argparse.ArgumentParser(prog="artcode")
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--config", type=Path)
    args = parser.parse_args()
    try:
        return asyncio.run(run_app(config_path=args.config, workspace_path=args.workspace))
    except KeyboardInterrupt:
        TuiRenderer().show_exit()
        return 130
