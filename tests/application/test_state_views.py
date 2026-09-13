from __future__ import annotations

from pathlib import Path

from artcode._application import LocalApplication
from tests.application.conftest import FakeModel, options


async def test_state_views_are_read_only_and_do_not_consume_notice(tmp_path: Path) -> None:
    app = await LocalApplication.create(options(tmp_path), model=FakeModel())
    app.session.add_notice("pending")
    before = app.snapshot().session

    await app.handle("/status")
    await app.handle("/session")
    await app.handle("/memory")
    await app.handle("/tasks")

    after = app.snapshot().session
    assert after.pending_notices == before.pending_notices == ("pending",)
    assert after.facts == before.facts
    await app.close()
