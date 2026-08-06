from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from artcode.agent import NORMAL_AGENT_MODE
from artcode.context_management.models import CompressionReport, CompressionTrigger
from artcode.persistence import (
    PersistenceCoordinator,
    SessionError,
    SessionJournal,
    SessionLockedError,
    SessionSelection,
)
from artcode.prompting.assembler import PromptRequestAssembler
from artcode.tools import AllowedPathPolicy, ToolExecutionContext
from artcode.workspace import ArtCodePaths, Workspace


class UnusedProvider:
    async def stream_chat(self, messages, tools=None, *, options=None):
        if False:
            yield {}


def _context(tmp_path: Path):
    home = ArtCodePaths.create(tmp_path / "home")
    project = tmp_path / "project"
    project.mkdir()
    return home, Workspace.from_path(project)


async def test_coordinator_new_then_default_resume_restores_conversation_and_plan(tmp_path: Path) -> None:
    app_paths, workspace = _context(tmp_path)
    first = PersistenceCoordinator.start(
        app_paths, workspace, UnusedProvider(), SessionSelection.new()
    )
    session_id = first.status.session_id
    first.conversation.append_user("制定计划", mode="plan")
    first.conversation.append_assistant("计划 A", mode="plan")
    await first.close()

    resumed = PersistenceCoordinator.start(
        app_paths, workspace, UnusedProvider(), SessionSelection.latest()
    )
    try:
        assert resumed.status.restored
        assert resumed.status.session_id == session_id
        assert resumed.status.recovered_messages == 2
        assert resumed.plan_memory.get() == "计划 A"
        new_entry = resumed.conversation.append_user("继续")
        assert new_entry.id == "msg-00000004"
    finally:
        path = resumed.journal.path
        await resumed.close()
    SessionJournal.open_existing(path).close()


async def test_default_locked_latest_creates_new_but_exact_resume_fails(tmp_path: Path) -> None:
    app_paths, workspace = _context(tmp_path)
    active = PersistenceCoordinator.start(
        app_paths, workspace, UnusedProvider(), SessionSelection.new()
    )
    active.conversation.append_user("locked")

    fallback = PersistenceCoordinator.start(
        app_paths, workspace, UnusedProvider(), SessionSelection.latest()
    )
    try:
        assert not fallback.status.restored
        assert fallback.status.default_locked_new_session
        assert fallback.status.session_id != active.status.session_id
        with pytest.raises(SessionLockedError):
            PersistenceCoordinator.start(
                app_paths,
                workspace,
                UnusedProvider(),
                SessionSelection.resume(active.status.session_id),
            )
    finally:
        await fallback.close()
        await active.close()


def test_exact_resume_rejects_bad_or_missing_id(tmp_path: Path) -> None:
    app_paths, workspace = _context(tmp_path)
    with pytest.raises(SessionError, match="格式非法"):
        PersistenceCoordinator.start(
            app_paths, workspace, UnusedProvider(), SessionSelection.resume("bad")
        )
    with pytest.raises(SessionError, match="找不到"):
        PersistenceCoordinator.start(
            app_paths,
            workspace,
            UnusedProvider(),
            SessionSelection.resume("20260806-000000-dead"),
        )


async def test_gap_reminder_and_restore_preparation_run_once(tmp_path: Path) -> None:
    app_paths, workspace = _context(tmp_path)
    first = PersistenceCoordinator.start(
        app_paths, workspace, UnusedProvider(), SessionSelection.new()
    )
    first.conversation.append_user("old")
    session_id = first.status.session_id
    path = first.journal.path
    await first.close()
    line = json.loads(path.read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc)
    line["timestamp"] = (now - timedelta(hours=25)).isoformat().replace("+00:00", "Z")
    path.write_text(json.dumps(line) + "\n", encoding="utf-8")

    resumed = PersistenceCoordinator.start(
        app_paths,
        workspace,
        UnusedProvider(),
        SessionSelection.resume(session_id),
        now,
    )

    class FakeConfig:
        automatic_threshold = 1

    class FakeManager:
        config = FakeConfig()

        def run_lightweight(self, conversation):
            return None

        def estimate_request(self, request):
            return 2

        async def compact(self, conversation, trigger):
            assert trigger is CompressionTrigger.RESTORE
            return CompressionReport(trigger, "success", 2, 1)

    assembler = PromptRequestAssembler(durable_prompt=resumed.prompt_context)
    tool_context = ToolExecutionContext(
        AllowedPathPolicy((workspace.root,)), default_cwd=workspace.root
    )
    try:
        report = await resumed.prepare_restored_context(
            FakeManager(), assembler, NORMAL_AGENT_MODE, [], tool_context
        )
        second = await resumed.prepare_restored_context(
            FakeManager(), assembler, NORMAL_AGENT_MODE, [], tool_context
        )
        first_request = assembler.assemble(
            resumed.conversation.export_messages(), NORMAL_AGENT_MODE, [], tool_context
        )
        next_request = assembler.assemble(
            resumed.conversation.export_messages(), NORMAL_AGENT_MODE, [], tool_context
        )
        assert report.attempted and report.status == "success"
        assert second.status == "already_prepared"
        assert "超过 24 小时" in str(first_request.messages)
        assert "超过 24 小时" not in str(next_request.messages)
    finally:
        await resumed.close()
