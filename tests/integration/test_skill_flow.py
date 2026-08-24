from __future__ import annotations

from pathlib import Path

from artcode.agent import AgentLoop, AgentRunRequest, NORMAL_AGENT_MODE, RequestPreparer
from artcode.agent.events import AgentEventType, StopReason
from artcode.conversation import ConversationContext
from artcode.permissions import PermissionState
from artcode.permissions.service import PermissionService
from artcode.prompting.assembler import PromptRequestAssembler
from artcode.providers.events import content_delta_event, done_event, tool_calls_event
from artcode.providers.tool_calls import ToolCall
from artcode.skills import LoadSkillTool, SkillService
from artcode.tools import ToolEnvironment, create_default_tool_registry
from artcode.tools.execution import ToolExecutionService


class ScriptedProvider:
    def __init__(self, responses) -> None:
        self.responses = list(responses)
        self.requests = []

    async def stream(self, request):
        self.requests.append(request)
        for event in self.responses.pop(0):
            yield event


async def test_model_loads_skill_then_next_request_receives_sop_and_restricted_tools(tmp_path: Path) -> None:
    project, user, builtin = _roots(tmp_path)
    _write_skill(project / "review.md", model="specialist-model")
    registry = create_default_tool_registry()
    service = SkillService.from_paths(
        project,
        user,
        builtin,
        known_tool_names={item.name for item in registry.descriptors()},
    )
    service.start()
    registry.register(LoadSkillTool(service))
    provider = ScriptedProvider(
        [
            [tool_calls_event([ToolCall("load", "load_skill", '{"name":"review"}')]), done_event()],
            [content_delta_event("完成"), done_event()],
        ]
    )
    conversation = ConversationContext()
    environment = ToolEnvironment.from_workspace(tmp_path)
    state = PermissionState()
    preparer = RequestPreparer(
        conversation,
        PromptRequestAssembler(),
        registry,
        environment,
        state,
        skill_service=service,
    )
    loop = AgentLoop(
        provider,
        conversation,
        registry,
        environment,
        tool_executor=ToolExecutionService(registry, environment, PermissionService(state)),
        request_preparer=preparer,
    )

    events = [event async for event in loop.run(AgentRunRequest("review this", NORMAL_AGENT_MODE))]

    assert events[-1].payload["reason"] == StopReason.NATURAL.value
    first, second = provider.requests
    first_text = "\n".join(str(message.get("content", "")) for message in first.messages)
    second_text = "\n".join(str(message.get("content", "")) for message in second.messages)
    assert "review: Review code changes." in first_text
    assert "REVIEW SOP UNIQUE" not in first_text
    assert "REVIEW SOP UNIQUE" in second_text
    assert first.model is None
    assert second.model == "specialist-model"
    assert _tool_names(first) == {
        "read_file", "write_file", "edit_file", "run_command", "find_files", "search_text", "load_skill"
    }
    assert _tool_names(second) == {"read_file", "load_skill"}
    results = [event.payload["result"] for event in events if event.type is AgentEventType.TOOL_RESULT]
    assert results[0].ok


async def test_execution_rechecks_skill_tool_whitelist(tmp_path: Path) -> None:
    project, user, builtin = _roots(tmp_path)
    _write_skill(project / "review.md")
    registry = create_default_tool_registry()
    service = SkillService.from_paths(project, user, builtin, known_tool_names={item.name for item in registry.descriptors()})
    service.start()
    registry.register(LoadSkillTool(service))
    assert service.activate("review").ok
    provider = ScriptedProvider([[tool_calls_event([ToolCall("write", "write_file", '{"path":"x.txt","content":"x"}')]), done_event()]])
    conversation = ConversationContext()
    environment = ToolEnvironment.from_workspace(tmp_path)
    state = PermissionState()
    loop = AgentLoop(
        provider,
        conversation,
        registry,
        environment,
        tool_executor=ToolExecutionService(registry, environment, PermissionService(state)),
        request_preparer=RequestPreparer(
            conversation,
            PromptRequestAssembler(),
            registry,
            environment,
            state,
            skill_service=service,
        ),
    )

    events = [
        event
        async for event in loop.run(
            AgentRunRequest("try to write", NORMAL_AGENT_MODE, final_summary_on_abnormal_stop=False)
        )
    ]

    result = next(event.payload["result"] for event in events if event.type is AgentEventType.TOOL_RESULT)
    assert result.error_code == "tool_not_allowed"
    assert not (tmp_path / "x.txt").exists()


def _roots(tmp_path: Path) -> tuple[Path, Path, Path]:
    project, user, builtin = (tmp_path / "project", tmp_path / "user", tmp_path / "builtin")
    project.mkdir()
    user.mkdir()
    builtin.mkdir()
    return project, user, builtin


def _write_skill(path: Path, *, model: str | None = None) -> None:
    model_line = "" if model is None else f"\nmodel: {model}"
    path.write_text(
        "---\nname: review\ndescription: Review code changes.\ntools: [read_file]\nmode: shared"
        + model_line
        + "\n---\nREVIEW SOP UNIQUE",
        encoding="utf-8",
    )


def _tool_names(request) -> set[str]:
    return {tool["function"]["name"] for tool in request.tools or ()}
