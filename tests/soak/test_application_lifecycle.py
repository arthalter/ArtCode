from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from artcode.bootstrap import AppOptions, run_application
from artcode.persistence import SessionCatalog, SessionSelection
from tests.bootstrap_fakes import (
    BootstrapHarness,
    install_bootstrap_fakes,
    write_config,
)


pytestmark = [pytest.mark.ch10_5, pytest.mark.soak]


@pytest.mark.parametrize(
    ("inputs", "cancelled"),
    [
        (["/exit"], False),
        ([], False),
        (["   ", "/exit"], False),
        (["/status", "/exit"], False),
        (["__cancel__"], True),
    ],
    ids=("immediate", "eof", "empty", "status", "cancel"),
)
async def test_repeated_application_lifecycle_leaves_no_owned_resource(
    tmp_path: Path,
    monkeypatch,
    inputs: list[str],
    cancelled: bool,
) -> None:
    repeats = 5
    harness = BootstrapHarness()
    install_bootstrap_fakes(monkeypatch, harness)
    workspaces: list[Path] = []

    for index in range(repeats):
        root = tmp_path / f"run-{index}"
        workspace = root / "workspace"
        workspace.mkdir(parents=True)
        home = root / "home"
        options = AppOptions(
            write_config(home),
            workspace,
            home,
            SessionSelection.new(),
        )
        workspaces.append(workspace)
        harness.inputs = list(inputs)
        if cancelled:
            with pytest.raises(asyncio.CancelledError):
                await run_application(options)
        else:
            assert await run_application(options) == 0

    for name in ("provider", "session", "artifact", "seatbelt", "mcp", "memory"):
        assert harness.events.count(f"{name}:create") == repeats
        assert harness.events.count(f"{name}:close") == repeats
    for workspace in workspaces:
        assert list((workspace / ".artcode" / "context").iterdir()) == []
        assert all(
            not descriptor.locked
            for descriptor in SessionCatalog(
                workspace / ".artcode" / "sessions"
            ).list_recent()
        )
