from __future__ import annotations

from pathlib import Path

from artcode.agent import NORMAL_AGENT_MODE
from artcode.background import BackgroundTaskManager
from artcode.config import ContextConfig
from artcode.conversation import ConversationContext
from artcode.permissions import PermissionState
from artcode.permissions import PermissionMode
from artcode.providers.events import content_delta_event, done_event, tool_calls_event
from artcode.providers.tool_calls import ToolCall
from artcode.prompting.assembler import PromptRequest
from artcode.subagents import RoleCatalog
from artcode.subagents.factory import SubagentFactory
from artcode.subagents.tool import AgentTool
from artcode.tools import ToolEnvironment, ToolRunContext, create_default_tool_registry
from artcode.worktrees import WorktreeManager
from tests.fixtures.providers import ScriptedProvider
import subprocess


def _role(path: Path, name: str = "reader") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        f"name: {name}\n"
        "description: 只读核查\n"
        "tools:\n"
        "  allow: [read_file]\n"
        "  deny: []\n"
        "model: inherit\n"
        "max_rounds: 10\n"
        "permission_mode: default\n"
        "isolation: none\n"
        "---\n"
        "只阅读必要文件并返回结论。\n",
        encoding="utf-8",
    )


async def test_definition_and_fork_use_isolated_or_frozen_conversation(tmp_path: Path) -> None:
    role_dir = tmp_path / ".artcode" / "agents"
    _role(role_dir / "reader.md")
    parent = ConversationContext()
    parent.append_user("PARENT HISTORY UNIQUE")
    provider = ScriptedProvider.from_streams(
        (
            (content_delta_event("definition done"), done_event()),
            (content_delta_event("fork done"), done_event()),
        )
    )
    registry = create_default_tool_registry()
    environment = ToolEnvironment.from_workspace(tmp_path)
    catalog = RoleCatalog(
        project_dir=role_dir,
        user_dir=tmp_path / "user-agents",
        builtin_dir=tmp_path / "builtin-agents",
    )
    tasks = BackgroundTaskManager()
    factory = SubagentFactory(
        provider=provider,
        tool_registry=registry,
        base_environment=environment,
        permission_engine=None,
        context_config=ContextConfig(),
        worktrees=WorktreeManager(tmp_path),
        model_tiers={},
        background_tools=frozenset({
            "read_file", "write_file", "edit_file", "run_command", "find_files", "search_text"
        }),
    )
    tool = AgentTool(catalog, factory, tasks, parent)
    context = ToolRunContext(environment, NORMAL_AGENT_MODE, PermissionState().snapshot())

    definition = tool.prepare({"type": "definition", "task": "检查当前目录", "role": "reader"}, context)
    definition_result = await tool.execute(definition, context)
    assert definition_result.ok
    assert "definition done" in definition_result.content
    definition_payload = provider.requests[0]
    definition_text = "\n".join(str(message.get("content", "")) for message in definition_payload.messages)
    assert "PARENT HISTORY UNIQUE" not in definition_text

    fork = tool.prepare({"type": "fork", "task": "利用已有事实回答", "role": "reader"}, context)
    fork_result = await tool.execute(fork, context)
    assert fork_result.ok
    task_id = __import__("json").loads(fork_result.content)["task_id"]
    detail = await tasks.wait(task_id)
    assert detail is not None and detail.result is not None
    fork_payload = provider.requests[1]
    fork_text = "\n".join(str(message.get("content", "")) for message in fork_payload.messages)
    assert "PARENT HISTORY UNIQUE" in fork_text


async def test_fork_first_request_preserves_prepared_parent_prefix_and_tool_order(
    tmp_path: Path,
) -> None:
    role_dir = tmp_path / ".artcode" / "agents"
    _role(role_dir / "reader.md")
    registry = create_default_tool_registry()
    parent_tools = tuple(
        tool
        for tool in registry.openai_tools()
        if tool["function"]["name"] == "read_file"
    )
    parent_messages = (
        {"role": "system", "content": "PARENT SYSTEM EXACT"},
        {"role": "user", "content": "PARENT FACT EXACT"},
        {"role": "assistant", "content": "PARENT ANSWER EXACT"},
        {"role": "user", "content": "<system-reminder>exact parent reminder</system-reminder>"},
    )
    parent_request = PromptRequest(parent_messages, parent_tools)
    provider = ScriptedProvider.from_streams(
        ((content_delta_event("fork prefix done"), done_event()),)
    )
    environment = ToolEnvironment.from_workspace(tmp_path)
    tasks = BackgroundTaskManager(id_factory=lambda: "aabbccdd")
    factory = SubagentFactory(
        provider=provider,
        tool_registry=registry,
        base_environment=environment,
        permission_engine=None,
        context_config=ContextConfig(),
        worktrees=WorktreeManager(tmp_path),
        model_tiers={},
        background_tools=frozenset({"read_file"}),
    )
    tool = AgentTool(
        RoleCatalog(
            project_dir=role_dir,
            user_dir=tmp_path / "user",
            builtin_dir=tmp_path / "builtin",
        ),
        factory,
        tasks,
        ConversationContext(),
        parent_request_provider=lambda: parent_request,
        parent_policy_provider=lambda: NORMAL_AGENT_MODE.tool_policy,
    )
    context = ToolRunContext(
        environment, NORMAL_AGENT_MODE, PermissionState().snapshot()
    )

    prepared = tool.prepare(
        {"type": "fork", "task": "根据父事实回答", "role": "reader"},
        context,
    )
    result = await tool.execute(prepared, context)
    task_id = __import__("json").loads(result.content)["task_id"]
    detail = await tasks.wait(task_id)

    assert detail is not None and detail.result is not None
    child_request = provider.requests[0]
    assert tuple(child_request.messages[: len(parent_messages)]) == parent_messages
    assert tuple(child_request.tools or ()) == parent_tools
    assert child_request.messages[len(parent_messages)]["role"] == "system"
    assert any(
        message.get("role") == "user"
        and message.get("content") == "根据父事实回答"
        for message in child_request.messages[len(parent_messages) :]
    )
    assert detail.result.cache_prefix_preserved is True


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


async def test_writing_subagent_uses_a_retained_worktree(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "tests@example.com")
    _git(tmp_path, "config", "user.name", "Tests")
    (tmp_path / ".gitignore").write_text(".artcode/worktrees/\n", encoding="utf-8")
    (tmp_path / "main.txt").write_text("main\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "initial")
    role_dir = tmp_path / ".artcode" / "agents"
    (role_dir / "writer.md").parent.mkdir(parents=True)
    (role_dir / "writer.md").write_text(
        "---\nname: writer\ndescription: 隔离写入\ntools:\n  allow: [write_file]\n  deny: []\nmodel: inherit\nmax_rounds: 10\npermission_mode: edit\nisolation: worktree\n---\n只在隔离目录写文件。\n",
        encoding="utf-8",
    )
    provider = ScriptedProvider.from_streams(
        (
            (tool_calls_event([ToolCall("write", "write_file", '{"path":"child.txt","content":"from child\\n"}')]), done_event()),
            (content_delta_event("written"), done_event()),
        )
    )
    parent = ConversationContext()
    registry = create_default_tool_registry()
    environment = ToolEnvironment.from_workspace(tmp_path)
    tasks = BackgroundTaskManager()
    factory = SubagentFactory(
        provider=provider,
        tool_registry=registry,
        base_environment=environment,
        permission_engine=None,
        context_config=ContextConfig(),
        worktrees=WorktreeManager(tmp_path),
        model_tiers={},
        background_tools=frozenset({
            "read_file", "write_file", "edit_file", "run_command", "find_files", "search_text"
        }),
    )
    tool = AgentTool(
        RoleCatalog(project_dir=role_dir, user_dir=tmp_path / "user", builtin_dir=tmp_path / "builtin"),
        factory,
        tasks,
        parent,
    )
    state = PermissionState(mode=PermissionMode.EDIT)
    context = ToolRunContext(environment, NORMAL_AGENT_MODE, state.snapshot())

    prepared = tool.prepare({"type": "definition", "task": "写入隔离文件", "role": "writer"}, context)
    result = await tool.execute(prepared, context)

    assert result.ok
    assert not (tmp_path / "child.txt").exists()
    task_id = __import__("json").loads(result.content)["task_id"]
    detail = tasks.get(task_id)
    assert detail is not None and detail.result is not None
    handoff = detail.result.handoff
    assert handoff is not None and handoff.retained is True
    assert (handoff.path / "child.txt").read_text(encoding="utf-8") == "from child\n"
