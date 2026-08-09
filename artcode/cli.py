from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from artcode.bootstrap import AppOptions, run_application
from artcode.persistence import SessionSelection
from artcode.tui import TuiRenderer


async def run_app(options: AppOptions) -> int:
    try:
        return await run_application(options)
    except Exception as exc:
        TuiRenderer().show_startup_error(exc)
        return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="artcode")
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--config", type=Path)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--new", action="store_true", dest="new_session", help="始终创建新会话")
    selection.add_argument("--resume", metavar="SESSION_ID", help="精确恢复指定会话")
    return parser


def parse_options(args: argparse.Namespace) -> AppOptions:
    selection = (
        SessionSelection.new()
        if args.new_session
        else SessionSelection.resume(args.resume)
        if args.resume is not None
        else SessionSelection.latest()
    )
    return AppOptions(
        config_path=args.config,
        workspace_path=args.workspace,
        artcode_home=None,
        session_selection=selection,
    )


def main() -> int:
    options = parse_options(build_parser().parse_args())
    try:
        return asyncio.run(run_app(options))
    except KeyboardInterrupt:
        TuiRenderer().show_exit()
        return 130


__all__ = ["build_parser", "main", "parse_options", "run_app"]
