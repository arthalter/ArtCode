from __future__ import annotations

from contextlib import AsyncExitStack
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from artcode.bootstrap import AppOptions, Bootstrap, run_application
from artcode.cli import build_parser, parse_options
from artcode.persistence import SessionSelection, SessionSelectionMode
from artcode.workspace import Workspace
from tests.bootstrap_fakes import (
    BootstrapHarness,
    install_bootstrap_fakes,
    write_config,
)


pytestmark = pytest.mark.ch10_5


def _options(tmp_path: Path, selection: SessionSelection | None = None) -> AppOptions:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    home = tmp_path / "home"
    config = write_config(home)
    return AppOptions(
        config,
        workspace,
        home,
        selection or SessionSelection.new(),
    )


def test_app_options_are_immutable(tmp_path: Path) -> None:
    options = _options(tmp_path)
    with pytest.raises(FrozenInstanceError):
        options.workspace_path = tmp_path  # type: ignore[misc]


@pytest.mark.parametrize(
    ("argv", "mode", "session_id"),
    [
        ([], SessionSelectionMode.DEFAULT, None),
        (["--new"], SessionSelectionMode.NEW, None),
        (["--resume", "20260810-120000-a1b2"], SessionSelectionMode.RESUME, "20260810-120000-a1b2"),
    ],
    ids=("latest", "new", "exact-resume"),
)
def test_cli_parses_one_session_selection(argv, mode, session_id) -> None:
    options = parse_options(build_parser().parse_args(argv))
    assert options.session_selection.mode is mode
    assert options.session_selection.session_id == session_id


@pytest.mark.parametrize(
    "inputs",
    [
        ["/exit"],
        ["   ", "/exit"],
        [],
    ],
    ids=("immediate-command", "empty-then-command", "terminal-eof"),
)
async def test_bootstrap_runs_terminal_exit_paths_and_closes_in_reverse(
    tmp_path: Path,
    monkeypatch,
    inputs: list[str],
) -> None:
    harness = BootstrapHarness(inputs=list(inputs))
    install_bootstrap_fakes(monkeypatch, harness)

    assert await run_application(_options(tmp_path)) == 0
    closes = [event for event in harness.events if event.endswith(":close")]
    assert closes == [
        "memory:close",
        "mcp:close",
        "seatbelt:close",
        "artifact:close",
        "session:close",
        "provider:close",
    ]


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        ("model", "deepseek-v4-flash"),
        ("workspace", "workspace"),
        ("context_window_tokens", 200_000),
        ("session_state", "new"),
    ],
    ids=("model", "workspace", "context-window", "session"),
)
async def test_bootstrap_projects_startup_status_from_owned_components(
    tmp_path: Path,
    monkeypatch,
    field: str,
    expected,
) -> None:
    harness = BootstrapHarness()
    install_bootstrap_fakes(monkeypatch, harness)

    assert await run_application(_options(tmp_path)) == 0
    value = getattr(harness.startups[0], field)
    if field == "workspace":
        assert Path(value).name == expected
    else:
        assert value == expected


async def test_bootstrap_plain_message_uses_the_composed_agent_loop(
    tmp_path: Path,
    monkeypatch,
) -> None:
    harness = BootstrapHarness(inputs=["你好", "/exit"], response_text="你好，已接入。")
    install_bootstrap_fakes(monkeypatch, harness)

    assert await run_application(_options(tmp_path)) == 0
    assert harness.provider_requests
    assert "delta:你好，已接入。" in harness.events
    assert "stopped:natural" in harness.events


async def test_bootstrap_status_command_is_local(
    tmp_path: Path,
    monkeypatch,
) -> None:
    harness = BootstrapHarness(inputs=["/status", "/exit"])
    install_bootstrap_fakes(monkeypatch, harness)

    assert await run_application(_options(tmp_path)) == 0
    assert harness.provider_requests == []
    assert len(harness.runtime_statuses) == 1


async def test_build_returns_one_explicit_runtime_graph(
    tmp_path: Path,
    monkeypatch,
) -> None:
    harness = BootstrapHarness()
    install_bootstrap_fakes(monkeypatch, harness)
    options = _options(tmp_path)

    async with AsyncExitStack() as resources:
        application = await Bootstrap(options).build(resources)
        runtime = application.runtime
        assert runtime.workspace == Workspace.from_path(options.workspace_path)
        assert runtime.session_service.context.conversation is runtime.conversation
        assert runtime.agent_loop.conversation is runtime.conversation
        assert runtime.agent_loop.plan_memory is runtime.plan_memory
        assert runtime.tool_context.permission_state is runtime.state.permission

    context_root = options.workspace_path / ".artcode" / "context"
    assert list(context_root.iterdir()) == []
