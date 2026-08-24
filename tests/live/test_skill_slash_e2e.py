from __future__ import annotations

from pathlib import Path

import pytest

from artcode.agent import AgentLoop, PlanMemory, RequestPreparer
from artcode.commands import CommandDispatcher, create_default_registry, parse_input
from artcode.conversation import ConversationContext
from artcode.permissions import PermissionState
from artcode.permissions.service import PermissionService
from artcode.prompting.assembler import PromptRequestAssembler
from artcode.providers import DeepSeekChatProvider
from artcode.runtime import ArtCodeRuntime, RuntimeState
from artcode.skills import LoadSkillTool, SkillService
from artcode.tools import ToolEnvironment, create_default_tool_registry
from artcode.tools.execution import ToolExecutionService
from artcode.workspace import Workspace
from tests.live.conftest import load_live_config


pytestmark = pytest.mark.live


class RecordingTui:
    def __init__(self) -> None:
        self.deltas: list[str] = []
        self.stops: list[str] = []

    def set_display_mode(self, mode) -> None:
        pass

    def show_user_label(self) -> None:
        pass

    def show_assistant_label(self) -> None:
        pass

    def show_agent_iteration(self, current: int, maximum: int | None) -> None:
        pass

    def stream_delta(self, text: str) -> None:
        self.deltas.append(text)

    def finish_assistant_message(self) -> None:
        pass

    def show_tool_calls_received(self, count: int) -> None:
        pass

    def show_tool_batch_started(self, batch_index: int, safety: str, count: int) -> None:
        pass

    def show_tool_result_summary(self, result) -> None:
        pass

    def show_token_usage(self, *args) -> None:
        pass

    def show_agent_stopped(self, reason: str, message: str = "") -> None:
        self.stops.append(reason)

    def show_context_status(self, payload: dict) -> None:
        pass

    def show_persistence_status(self, payload: dict) -> None:
        pass


async def test_live_slash_skill_executes_against_configured_model_service(tmp_path: Path) -> None:
    config = load_live_config()
    workspace = Workspace.from_path(tmp_path)
    project, user, builtin = (tmp_path / "project", tmp_path / "user", tmp_path / "builtin")
    for root in (project, user, builtin):
        root.mkdir()
    (project / "slashok.md").write_text(
        "---\nname: slashok\ndescription: Reply with SLASH_OK.\ntools: []\nmode: shared\n---\nReply with exactly: SLASH_OK",
        encoding="utf-8",
    )
    registry = create_default_tool_registry()
    service = SkillService.from_paths(
        project,
        user,
        builtin,
        known_tool_names={item.name for item in registry.descriptors()},
        reserved_commands={item.name for item in create_default_registry().definitions()},
    )
    service.start()
    registry.register(LoadSkillTool(service))
    conversation = ConversationContext()
    environment = ToolEnvironment.from_workspace(workspace)
    state = RuntimeState(PermissionState())
    provider = DeepSeekChatProvider(config)
    tui = RecordingTui()
    try:
        loop = AgentLoop(
            provider,
            conversation,
            registry,
            environment,
            tool_executor=ToolExecutionService(registry, environment, PermissionService(state.permission)),
            request_preparer=RequestPreparer(
                conversation,
                PromptRequestAssembler(),
                registry,
                environment,
                state.permission,
                skill_service=service,
            ),
        )
        runtime = ArtCodeRuntime(
            config=config,
            conversation=conversation,
            tui=tui,
            workspace=workspace,
            state=state,
            tool_environment=environment,
            plan_memory=PlanMemory(),
            agent_loop=loop,
            command_dispatcher=CommandDispatcher(create_default_registry()),
            session_service=None,  # type: ignore[arg-type]
            memory_service=None,  # type: ignore[arg-type]
            startup_status=None,  # type: ignore[arg-type]
            mcp_report=None,  # type: ignore[arg-type]
            skill_service=service,
        )
        parsed = parse_input("/slashok")
        assert parsed.invocation is not None
        handled = await runtime._dispatch_skill_command(parsed.invocation)
    finally:
        await provider.close()

    if not handled or "stream_error" in tui.stops:
        pytest.skip("environment blocked: live provider request failed during slash Skill execution")
    assert tui.stops[-1] == "natural"
    assert conversation.export_messages()[-1]["content"].strip() == "SLASH_OK"
    assert state.last_token_usage is not None
