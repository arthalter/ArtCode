from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

pytestmark = pytest.mark.live

from artcode.agent import AgentLoop, AgentRunRequest, NORMAL_AGENT_MODE, NaturalTurn
from artcode.config import ArtCodeConfig, ConfigError, load_config
from artcode.persistence import (
    MemoryNoteStore,
    MemoryScope,
    MemoryUpdater,
    PersistenceCoordinator,
    SessionSelection,
)
from artcode.prompting.assembler import PromptRequestAssembler
from artcode.providers.openai_compatible import OpenAICompatibleProvider
from artcode.providers.events import CONTENT_DELTA
from artcode.tools import AllowedPathPolicy, ToolExecutionContext, ToolRegistry
from artcode.workspace import ArtCodePaths, Workspace


ROOT = Path(__file__).resolve().parents[2]


class CapturingProvider:
    def __init__(self, inner) -> None:
        self.inner = inner
        self.responses: list[str] = []

    async def stream_chat(self, messages, tools=None, *, options=None):
        parts = []
        async for event in self.inner.stream_chat(messages, tools, options=options):
            if event.get("type") == CONTENT_DELTA:
                parts.append(event.get("text", ""))
            yield event
        self.responses.append("".join(parts))


def required_live_config() -> ArtCodeConfig:
    try:
        config = load_config(ROOT / "artcode.yaml")
    except ConfigError as exc:
        pytest.fail(f"ch09 live memory validation requires real API config: {exc.message}")
    if "your-deepseek-api-key" in config.api_key or config.api_key.startswith("<"):
        pytest.fail("ch09 live memory validation requires a real API key in artcode.yaml")
    return replace(config, model="deepseek-v4-flash")


async def test_live_memory_extracts_cross_project_preference_and_deduplicates(tmp_path: Path) -> None:
    config = required_live_config()
    provider = CapturingProvider(OpenAICompatibleProvider(config))
    app_paths = ArtCodePaths.create(tmp_path / "home")
    workspace_root = tmp_path / "project"
    workspace_root.mkdir()
    workspace = Workspace.from_path(workspace_root)
    user = MemoryNoteStore(app_paths.user_memory_dir, MemoryScope.USER)
    project = MemoryNoteStore(workspace.project_memory_dir, MemoryScope.PROJECT)
    updater = MemoryUpdater(provider, user, project, secrets=(config.api_key,))
    first = NaturalTurn(
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

    second = NaturalTurn(
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

    resumed = PersistenceCoordinator.start(
        app_paths,
        workspace,
        provider,
        SessionSelection.new(),
        secrets=(config.api_key,),
    )
    context = ToolExecutionContext(
        AllowedPathPolicy((workspace.root,)), default_cwd=workspace.root
    )
    loop = AgentLoop(
        provider,
        resumed.conversation,
        ToolRegistry(),
        context,
        request_assembler=PromptRequestAssembler(durable_prompt=resumed.prompt_context),
        natural_turn_observer=resumed.turn_observer,
        session_id=resumed.status.session_id,
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
        await resumed.close()
