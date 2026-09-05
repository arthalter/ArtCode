from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from artcode._application import LocalApplication
from artcode.adapters import TerminalAdapter, run_terminal
from artcode.core.application import ApplicationOptions
from artcode.core.session import SessionSelection


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="artcode")
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--config", type=Path)
    parser.add_argument("--artcode-home", type=Path)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--new", action="store_true", dest="new_session")
    selection.add_argument("--resume", metavar="SESSION_ID")
    return parser


def parse_options(args: argparse.Namespace) -> ApplicationOptions:
    home = (args.artcode_home or (Path.home() / ".artcode")).expanduser().resolve(strict=False)
    config = (args.config or (home / "config.yml")).expanduser().resolve(strict=False)
    workspace = args.workspace.expanduser().resolve(strict=False)
    selection = (
        SessionSelection.new()
        if args.new_session
        else SessionSelection.exact(args.resume)
        if args.resume is not None
        else SessionSelection.latest()
    )
    return ApplicationOptions(workspace, config, home, selection)


async def run_app(options: ApplicationOptions) -> int:
    terminal = TerminalAdapter()
    try:
        application = await LocalApplication.create(options, interaction=terminal)
    except Exception as exc:
        terminal.console.print(f"[red]{exc}[/red]")
        return 2
    return await run_terminal(application, terminal)


def main() -> int:
    options = parse_options(build_parser().parse_args())
    try:
        return asyncio.run(run_app(options))
    except KeyboardInterrupt:
        return 130


__all__ = ["build_parser", "main", "parse_options", "run_app"]
