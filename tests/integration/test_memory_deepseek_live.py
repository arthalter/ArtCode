from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.live

from artcode.agent import AgentLoop, AgentRunRequest, NORMAL_AGENT_MODE, CompletedTurn, RequestPreparer
from artcode.config import ArtCodeConfig
from artcode.persistence import (
    DurablePaths,
    DurablePromptSource,
    MemoryService,
    MemoryNoteStore,
    MemoryScope,
    MemoryUpdater,
    SessionSelection,
    SessionService,
)
from artcode.permissions import PermissionState
from artcode.permissions.service import PermissionService
from artcode.prompting.assembler import PromptRequestAssembler
from artcode.providers import DeepSeekChatProvider
from artcode.providers.events import ContentDelta
from artcode.tools import ToolEnvironment, ToolRegistry
from artcode.tools.execution import ToolExecutionService
from artcode.workspace import ArtCodePaths, Workspace
from tests.live.conftest import load_live_config


ROOT = Path(__file__).resolve().parents[2]


class CapturingProvider:
    def __init__(self, inner) -> None:
        self.inner = inner
        self.responses: list[str] = []

    async def stream(self, request):
        parts = []
        async for event in self.inner.stream(request):
            if isinstance(event, ContentDelta):
                parts.append(event.text)
            yield event
        self.responses.append("".join(parts))


def required_live_config() -> ArtCodeConfig:
    return load_live_config()


async def test_live_memory_extracts_cross_project_preference_and_deduplicates(tmp_path: Path) -> None:
    config = required_live_config()
    provider = CapturingProvider(DeepSeekChatProvider(config))
    app_paths = ArtCodePaths.create(tmp_path / "home")
    workspace_root = tmp_path / "project"
    workspace_root.mkdir()
    workspace = Workspace.from_path(workspace_root)
    user = MemoryNoteStore(app_paths.user_memory_dir, MemoryScope.USER)
    project = MemoryNoteStore(workspace.project_memory_dir, MemoryScope.PROJECT)
    updater = MemoryUpdater(provider, user, project, secrets=(config.api_key,))
    first = CompletedTurn(
        "20260806-120000-a1b2",
        "normal",
        "这是明确、长期且跨项目通用的偏好：我希望 Python 测试函数统一使用 test_should_ 前缀。请确认。",
        "已确认：以后在所有项目中，Python 测试函数优先使用 test_should_ 前缀。",
        ("msg-00000002", "msg-00000003"),
    )

    first_reports = []
    for _ in range(3):
        report = await updater.update(first)
        first_reports.append(report)
        if report.status == "success" and report.created + report.updated > 0:
            break

    assert report.status == "success", {
        "reports": [item.message for item in first_reports],
        "responses": provider.responses,
    }
    first_active = [note for note in user.scan().notes if note.status.value == "active"]
    assert len(first_active) == 1
    assert "test_should_" in (first_active[0].summary + first_active[0].body)
    assert not project.scan().notes

    second = CompletedTurn(
        "20260806-120000-a1b2",
        "normal",
        "再次确认同一偏好：所有项目的 Python 测试函数使用 test_should_ 前缀。",
        "已再次确认，没有新增不同偏好。",
        ("msg-00000004", "msg-00000005"),
    )
    second_reports = []
    for _ in range(3):
        duplicate_report = await updater.update(second)
        second_reports.append(duplicate_report)
        if duplicate_report.status == "success":
            break

    assert duplicate_report.status == "success", {
        "reports": [item.message for item in second_reports],
        "responses": provider.responses,
    }
    second_active = [note for note in user.scan().notes if note.status.value == "active"]
    assert len(second_active) == 1

    paths = DurablePaths.from_context(app_paths, workspace)
    sessions = SessionService(paths)
    resumed = sessions.start(SessionSelection.new())
    memory = MemoryService(paths, provider, secrets=(config.api_key,))
    environment = ToolEnvironment.from_workspace(workspace)
    permission_state = PermissionState()
    registry = ToolRegistry()
    loop = AgentLoop(
        provider,
        resumed.conversation,
        registry,
        environment,
        tool_executor=ToolExecutionService(
            registry,
            environment,
            PermissionService(permission_state),
        ),
        request_preparer=RequestPreparer(
            resumed.conversation,
            PromptRequestAssembler(),
            registry,
            environment,
            permission_state,
            durable_prompt=DurablePromptSource(paths),
        ),
        natural_turn_observer=memory,
        session_id=sessions.status.session_id,
    )
    try:
        async for _ in loop.run(
            AgentRunRequest(
                "根据长期记忆，我偏好的 Python 测试函数前缀是什么？只回复前缀。",
                NORMAL_AGENT_MODE,
            )
        ):
            pass
        assert "test_should_" in resumed.conversation.export_messages()[-1]["content"]
    finally:
        await memory.close()
        sessions.close()
