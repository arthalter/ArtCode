from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from artcode.agent import CompletedTurn
from artcode.persistence import (
    DurablePaths,
    MemoryService,
    MemoryUpdateReport,
    SessionJournal,
    SessionSelection,
    SessionService,
)
from artcode.workspace import ArtCodePaths, Workspace


pytestmark = [pytest.mark.ch10_5, pytest.mark.soak]
NOW = datetime(2026, 8, 10, 15, 0, tzinfo=timezone.utc)


class UnusedProvider:
    async def stream_chat(self, messages, tools=None, *, options=None):
        if False:
            yield {}


class RecordingUpdater:
    def __init__(self, order: list[str]) -> None:
        self.order = order

    async def update(self, turn: CompletedTurn) -> MemoryUpdateReport:
        self.order.append(turn.user_content)
        return MemoryUpdateReport("success")


def _paths(tmp_path: Path) -> DurablePaths:
    project = tmp_path / "project"
    project.mkdir()
    return DurablePaths.from_context(
        ArtCodePaths.create(tmp_path / "home"), Workspace.from_path(project)
    )


@pytest.mark.parametrize("cycles", [5, 10, 15, 20, 25])
async def test_repeated_session_memory_lifecycle_releases_every_resource(
    tmp_path: Path,
    cycles: int,
) -> None:
    paths = _paths(tmp_path)
    initial = SessionService(paths)
    context = initial.start(SessionSelection.new(), NOW)
    context.conversation.append_user("seed")
    session_id = context.status.session_id
    journal_path = initial.journal.path
    initial.close()

    expected_users = ["seed"]
    expected_memory_order: list[str] = []
    actual_memory_order: list[str] = []
    for cycle in range(cycles):
        sessions = SessionService(paths)
        restored = sessions.start(SessionSelection.resume(session_id), NOW)
        user_text = f"user-{cycle}"
        restored.conversation.append_user(user_text)
        restored.conversation.append_assistant(f"assistant-{cycle}")
        expected_users.append(user_text)
        journal = sessions.journal
        sessions.close()
        assert journal.closed
        SessionJournal.open_existing(journal_path).close()

        memory = MemoryService(
            paths,
            UnusedProvider(),
            updater=RecordingUpdater(actual_memory_order),
        )
        for item in range(3):
            content = f"memory-{cycle}-{item}"
            expected_memory_order.append(content)
            memory.submit(
                CompletedTurn(
                    session_id,
                    "normal",
                    content,
                    "done",
                    ("msg-00000002", "msg-00000003"),
                )
            )
        await memory.wait_idle()
        await memory.close()
        assert memory.pending_count == 0
        assert memory.worker._task is None

    final = SessionService(paths)
    recovered = final.start(SessionSelection.resume(session_id), NOW)
    try:
        actual_users = [
            message["content"]
            for message in recovered.conversation.export_messages()
            if message["role"] == "user"
        ]
        assert actual_users == expected_users
        assert actual_memory_order == expected_memory_order
        assert not list(paths.user_memory_dir.glob(".*.tmp"))
        assert not list(paths.project_memory_dir.glob(".*.tmp"))
        assert journal_path.stat().st_size > 0
    finally:
        final.close()
    SessionJournal.open_existing(journal_path).close()
