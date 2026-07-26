from pathlib import Path

import pytest

from artcode.permissions import (
    PermissionAction,
    PermissionEngine,
    PermissionMode,
    PermissionRequest,
    PermissionState,
    RuleLoader,
    RulePaths,
    ShellPolicy,
)
from artcode.security import DangerousCommandValidator


def engine(tmp_path: Path) -> PermissionEngine:
    return PermissionEngine(
        RuleLoader(RulePaths(tmp_path / "u", tmp_path / "p", tmp_path / "l")),
        DangerousCommandValidator.load(),
    )


@pytest.mark.parametrize(
    ("mode", "tool", "expected"),
    [
        (PermissionMode.DEFAULT, "read_file", PermissionAction.ALLOW),
        (PermissionMode.DEFAULT, "write_file", PermissionAction.ASK),
        (PermissionMode.EDIT, "write_file", PermissionAction.ALLOW),
        (PermissionMode.FULL, "edit_file", PermissionAction.ALLOW),
    ],
)
def test_file_mode_matrix(
    tmp_path: Path,
    mode: PermissionMode,
    tool: str,
    expected: PermissionAction,
) -> None:
    decision = engine(tmp_path).decide(
        PermissionRequest(tool, "a.txt", tmp_path),
        PermissionState(mode=mode),
    )
    assert decision.action is expected


@pytest.mark.parametrize(
    ("policy", "expected"),
    [
        (ShellPolicy.SANDBOX_AUTO, PermissionAction.ALLOW),
        (ShellPolicy.SANDBOX_ASK, PermissionAction.ASK),
        (ShellPolicy.UNSANDBOXED_ASK, PermissionAction.ASK),
    ],
)
def test_shell_policy_matrix(
    tmp_path: Path,
    policy: ShellPolicy,
    expected: PermissionAction,
) -> None:
    decision = engine(tmp_path).decide(
        PermissionRequest("run_command", "git status", tmp_path),
        PermissionState(shell_policy=policy),
    )
    assert decision.action is expected


def test_plan_write_is_hard_denied_before_rules(tmp_path: Path) -> None:
    (tmp_path / "l").write_text(
        "rules:\n- match: write_file(**)\n  action: allow\n",
        encoding="utf-8",
    )
    decision = engine(tmp_path).decide(
        PermissionRequest("write_file", "a.txt", tmp_path, plan_mode=True),
        PermissionState(mode=PermissionMode.FULL),
    )
    assert decision.action is PermissionAction.DENY
    assert decision.source.value == "plan"


def test_dangerous_command_is_hard_denied_before_allow_rule(tmp_path: Path) -> None:
    (tmp_path / "l").write_text(
        "rules:\n- match: run_command(**)\n  action: allow\n",
        encoding="utf-8",
    )
    decision = engine(tmp_path).decide(
        PermissionRequest("run_command", "git reset --hard", tmp_path),
        PermissionState(),
    )
    assert decision.action is PermissionAction.DENY
    assert "git-reset-hard" in decision.reason
