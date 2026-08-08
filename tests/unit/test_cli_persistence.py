from __future__ import annotations

import pytest

from artcode.cli import build_parser


def test_cli_session_selection_defaults_and_exact_values() -> None:
    parser = build_parser()

    default = parser.parse_args([])
    new = parser.parse_args(["--new"])
    resumed = parser.parse_args(["--resume", "20260806-120000-a1b2"])

    assert not default.new_session and default.resume is None
    assert new.new_session and new.resume is None
    assert not resumed.new_session and resumed.resume == "20260806-120000-a1b2"


def test_cli_new_and_resume_are_mutually_exclusive() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--new", "--resume", "20260806-120000-a1b2"])
