from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

import artcode.cli as cli
from artcode.bootstrap import AppOptions, run_application
from artcode.persistence import SessionSelection
from tests.bootstrap_fakes import (
    BootstrapHarness,
    install_bootstrap_fakes,
    write_config,
)


pytestmark = [pytest.mark.ch10_5, pytest.mark.fault]


def _options(root: Path) -> AppOptions:
    workspace = root / "workspace"
    workspace.mkdir(parents=True)
    home = root / "home"
    return AppOptions(
        write_config(home),
        workspace,
        home,
        SessionSelection.new(),
    )


async def test_every_startup_failure_closes_only_created_resources_once(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cases = {
        "provider": [],
        "session": ["session:close", "provider:close"],
        "artifact": ["artifact:close", "session:close", "provider:close"],
        "seatbelt": [
            "seatbelt:close",
            "artifact:close",
            "session:close",
            "provider:close",
        ],
        "mcp": [
            "mcp:close",
            "seatbelt:close",
            "artifact:close",
            "session:close",
            "provider:close",
        ],
        "prompt": [
            "memory:close",
            "mcp:close",
            "seatbelt:close",
            "artifact:close",
            "session:close",
            "provider:close",
        ],
    }
    for index, (stage, expected) in enumerate(cases.items()):
        harness = BootstrapHarness(failure_stage=stage)
        with monkeypatch.context() as scoped:
            install_bootstrap_fakes(scoped, harness)
            with pytest.raises(RuntimeError, match="failure"):
                await run_application(_options(tmp_path / f"case-{index}"))
        closes = [event for event in harness.events if event.endswith(":close")]
        assert closes == expected
        assert len(closes) == len(set(closes))


async def test_cancellation_propagates_after_reverse_cleanup(
    tmp_path: Path,
    monkeypatch,
) -> None:
    harness = BootstrapHarness(inputs=["__cancel__"])
    install_bootstrap_fakes(monkeypatch, harness)

    with pytest.raises(asyncio.CancelledError):
        await run_application(_options(tmp_path))

    assert [event for event in harness.events if event.endswith(":close")] == [
        "memory:close",
        "mcp:close",
        "seatbelt:close",
        "artifact:close",
        "session:close",
        "provider:close",
    ]


async def test_close_exception_does_not_skip_remaining_resources(
    tmp_path: Path,
    monkeypatch,
) -> None:
    harness = BootstrapHarness(close_failure="mcp")
    install_bootstrap_fakes(monkeypatch, harness)

    with pytest.raises(RuntimeError, match="mcp close failure"):
        await run_application(_options(tmp_path))

    assert [event for event in harness.events if event.endswith(":close")] == [
        "memory:close",
        "mcp:close",
        "seatbelt:close",
        "artifact:close",
        "session:close",
        "provider:close",
    ]

    exits: list[str] = []

    class Renderer:
        def show_exit(self) -> None:
            exits.append("exit")

    class Parser:
        def parse_args(self):
            return object()

    def interrupt(coroutine):
        coroutine.close()
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "TuiRenderer", Renderer)
    monkeypatch.setattr(cli, "build_parser", lambda: Parser())
    monkeypatch.setattr(cli, "parse_options", lambda _args: _options(tmp_path / "ctrl-c"))
    monkeypatch.setattr(cli.asyncio, "run", interrupt)
    assert cli.main() == 130
    assert exits == ["exit"]
