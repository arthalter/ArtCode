from __future__ import annotations

import asyncio
from pathlib import Path

from .config import load_config
from .conversation import ConversationContext
from .errors import ConfigError
from .providers import OpenAICompatibleProvider
from .runtime import ArtCodeRuntime
from .tools import AllowedPathPolicy, ToolExecutionContext, create_default_tool_registry
from .tui import PromptToolkitTui, TuiRenderer


async def run_app(config_path: Path | None = None) -> int:
    renderer = TuiRenderer()
    try:
        config = load_config(config_path)
    except ConfigError as exc:
        renderer.show_startup_error(exc)
        return 2

    provider = OpenAICompatibleProvider(config)
    path_policy = AllowedPathPolicy(config.tools.allowed_dirs)
    runtime = ArtCodeRuntime(
        config=config,
        provider=provider,
        conversation=ConversationContext(),
        tui=PromptToolkitTui(renderer=renderer),
        tool_registry=create_default_tool_registry(),
        tool_context=ToolExecutionContext(path_policy, default_cwd=config.tools.allowed_dirs[0]),
    )
    return await runtime.run()


def main() -> int:
    try:
        return asyncio.run(run_app())
    except KeyboardInterrupt:
        TuiRenderer().show_exit()
        return 130
