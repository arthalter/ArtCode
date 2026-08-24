from __future__ import annotations

from pathlib import Path

import pytest

from artcode.agent import AgentEventType, AgentLoop, AgentRunRequest, NORMAL_AGENT_MODE, RequestPreparer
from artcode.conversation import ConversationContext
from artcode.permissions import PermissionState
from artcode.permissions.service import PermissionService
from artcode.prompting.assembler import PromptRequestAssembler
from artcode.providers import DeepSeekChatProvider
from artcode.skills import LoadSkillTool, SkillService
from artcode.tools import ToolEnvironment, create_default_tool_registry
from artcode.tools.execution import ToolExecutionService
from tests.live.conftest import load_live_config


pytestmark = pytest.mark.live


async def test_live_model_can_load_a_skill_and_observe_its_sop(tmp_path: Path) -> None:
    config = load_live_config()
    project, user, builtin = (tmp_path / "project", tmp_path / "user", tmp_path / "builtin")
    for root in (project, user, builtin):
        root.mkdir()
    (project / "replyok.md").write_text(
        "---\nname: replyok\ndescription: Reply with the exact word OK.\ntools: []\nmode: shared\n---\nYou must answer exactly: OK",
        encoding="utf-8",
    )
    registry = create_default_tool_registry()
    service = SkillService.from_paths(project, user, builtin, known_tool_names={item.name for item in registry.descriptors()})
    service.start()
    registry.register(LoadSkillTool(service))
    conversation = ConversationContext()
    environment = ToolEnvironment.from_workspace(tmp_path)
    state = PermissionState()
    provider = DeepSeekChatProvider(config)
    try:
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
                AgentRunRequest(
                    "必须先实际调用函数 load_skill，参数 name 必须是 replyok；不要直接回答或只描述操作。工具结果返回后，再严格按该 Skill 回复。",
                    NORMAL_AGENT_MODE,
                )
            )
        ]
    finally:
        await provider.close()

    if any(
        event.type is AgentEventType.STOPPED and event.payload.get("reason") == "stream_error"
        for event in events
    ):
        pytest.skip("environment blocked: live provider request failed before a Skill response")
    tool_results = [event.payload["result"] for event in events if event.type is AgentEventType.TOOL_RESULT]
    assert tool_results and tool_results[0].tool_name == "load_skill" and tool_results[0].ok
    assert conversation.export_messages()[-1]["content"].strip() == "OK"
