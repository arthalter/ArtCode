from __future__ import annotations

from pathlib import Path

from artcode.config import ContextConfig
from artcode.subagents import RoleCatalog
from artcode.subagents.factory import SubagentFactory
from artcode.tools import ToolEnvironment, create_default_tool_registry
from artcode.worktrees import WorktreeManager

DEFAULT_BACKGROUND_TOOLS = frozenset(
    {"read_file", "write_file", "edit_file", "run_command", "find_files", "search_text"}
)


def write_role(
    path: Path,
    *,
    name: str,
    allow: list[str] | None = None,
    deny: list[str] | None = None,
    isolation: str = "none",
    permission_mode: str = "default",
    model: str = "inherit",
    max_rounds: int = 10,
    body: str = "完成给定的子任务并返回精简结论。",
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---" + chr(10)
        + f"name: {name}" + chr(10)
        + f"description: 测试角色 {name}" + chr(10)
        + "tools:" + chr(10)
        + f"  allow: [{', '.join(allow or [])}]" + chr(10)
        + f"  deny: [{', '.join(deny or [])}]" + chr(10)
        + f"model: {model}" + chr(10)
        + f"max_rounds: {max_rounds}" + chr(10)
        + f"permission_mode: {permission_mode}" + chr(10)
        + f"isolation: {isolation}" + chr(10)
        + "---" + chr(10)
        + f"{body}" + chr(10),
        encoding="utf-8",
    )
    return path


def make_catalog(
    workspace: Path,
    *,
    project: str = "agents",
    user: str = "user-agents",
    builtin: str = "builtin-agents",
) -> RoleCatalog:
    return RoleCatalog(
        project_dir=workspace / ".artcode" / project,
        user_dir=workspace / user,
        builtin_dir=workspace / builtin,
    )


def make_factory(
    *,
    provider,
    workspace: Path,
    registry=None,
    environment: ToolEnvironment | None = None,
    worktrees: WorktreeManager | None = None,
    background_tools: frozenset[str] = DEFAULT_BACKGROUND_TOOLS,
    model_tiers: dict[str, str] | None = None,
    permission_engine=None,
    context_config: ContextConfig | None = None,
) -> SubagentFactory:
    selected_registry = registry or create_default_tool_registry()
    return SubagentFactory(
        provider=provider,
        tool_registry=selected_registry,
        base_environment=environment or ToolEnvironment.from_workspace(workspace),
        permission_engine=permission_engine,
        context_config=context_config or ContextConfig(),
        worktrees=worktrees or WorktreeManager(workspace),
        model_tiers=model_tiers or {},
        background_tools=frozenset(background_tools),
    )
