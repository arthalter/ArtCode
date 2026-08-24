from __future__ import annotations

from pathlib import Path

from artcode.agent import AgentLoop, AgentRunRequest, NORMAL_AGENT_MODE, RequestPreparer
from artcode.conversation import ConversationContext
from artcode.permissions import PermissionState
from artcode.permissions.service import PermissionService
from artcode.prompting.assembler import PromptRequestAssembler
from artcode.providers.events import content_delta_event, done_event
from artcode.skills import LoadSkillTool, SkillService
from artcode.skills.execution import SkillExecutionCoordinator
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


async def test_isolated_skill_selects_complete_recent_history_and_returns_only_summary(tmp_path: Path) -> None:
    project, user, builtin = _roots(tmp_path)
    (project / "brief.md").write_text(
        "---\nname: brief\ndescription: Make a brief.\ntools: [read_file]\nmode: isolated\nhistory_turns: 1\nmodel: special-model\n---\nISOLATED SOP",
        encoding="utf-8",
    )
    registry = create_default_tool_registry()
    service = SkillService.from_paths(project, user, builtin, known_tool_names={item.name for item in registry.descriptors()})
    service.start()
    registry.register(LoadSkillTool(service))
    definition = service.activate("brief").definition
    assert definition is not None

    conversation = ConversationContext()
    conversation.append_user("old requirement")
    conversation.append_assistant("old response")
    conversation.append_user("recent requirement")
    conversation.append_assistant("recent response")
    provider = ScriptedProvider(
        [
            [content_delta_event("isolated summary"), done_event()],
            [content_delta_event("normal reply"), done_event()],
        ]
    )
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

    events = [event async for event in SkillExecutionCoordinator(loop).run(definition, "create the brief")]

    assert events[-1].payload["reason"] == "natural"
    child_request = provider.requests[0]
    child_text = "\n".join(str(item.get("content", "")) for item in child_request.messages)
    assert "ISOLATED SOP" in child_text
    assert "recent requirement" in child_text
    assert "old requirement" not in child_text
    assert child_request.model == "special-model"
    parent_messages = conversation.export_messages()
    assert parent_messages[-2:] == [
        {"role": "user", "content": "create the brief"},
        {"role": "assistant", "content": "isolated summary"},
    ]

    _ = [event async for event in loop.run(AgentRunRequest("normal", NORMAL_AGENT_MODE))]
    assert provider.requests[1].model is None


def _roots(tmp_path: Path) -> tuple[Path, Path, Path]:
    project, user, builtin = (tmp_path / "project", tmp_path / "user", tmp_path / "builtin")
    project.mkdir()
    user.mkdir()
    builtin.mkdir()
    return project, user, builtin
