from __future__ import annotations

import asyncio

import pytest

import artcode.cli as cli
from artcode.bootstrap import AppOptions
from artcode.persistence import SessionSelection


pytestmark = [pytest.mark.ch10_5, pytest.mark.soak]


@pytest.mark.parametrize(
    ("scenario", "selection"),
    [
        ("latest-success", SessionSelection.latest()),
        ("new-success", SessionSelection.new()),
        ("resume-success", SessionSelection.resume("20260810-120000-a1b2")),
        ("startup-error", SessionSelection.new()),
        ("cancel", SessionSelection.latest()),
    ],
    ids=("latest", "new", "exact-resume", "error", "cancel"),
)
async def test_repeated_cli_boundary_keeps_options_and_outcomes_isolated(
    monkeypatch,
    scenario: str,
    selection: SessionSelection,
) -> None:
    calls: list[AppOptions] = []
    errors: list[BaseException] = []

    async def fake_run(options: AppOptions) -> int:
        calls.append(options)
        if scenario == "startup-error":
            raise RuntimeError("startup failed")
        if scenario == "cancel":
            raise asyncio.CancelledError
        return 0

    class Renderer:
        def show_startup_error(self, error: BaseException) -> None:
            errors.append(error)

    monkeypatch.setattr(cli, "run_application", fake_run)
    monkeypatch.setattr(cli, "TuiRenderer", Renderer)
    options = AppOptions(None, None, None, selection)

    for _ in range(100):
        if scenario == "cancel":
            with pytest.raises(asyncio.CancelledError):
                await cli.run_app(options)
        else:
            expected = 2 if scenario == "startup-error" else 0
            assert await cli.run_app(options) == expected

    assert calls == [options] * 100
    assert len(errors) == (100 if scenario == "startup-error" else 0)
