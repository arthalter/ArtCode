from pathlib import Path

import pytest

from artcode.permissions import PermissionAction, PermissionRuleError
from artcode.permissions.rules import PermissionRule, RuleLoader, RulePaths


def test_expression_allows_parentheses_inside_pattern() -> None:
    rule = PermissionRule.parse('run_command(python -c "print(*)")', "allow")
    assert rule.pattern == 'python -c "print(*)"'
    assert rule.matches("run_command", 'python -c "print(1)"')


def test_same_layer_uses_last_matching_rule(tmp_path: Path) -> None:
    local = tmp_path / "local.yml"
    local.write_text(
        "rules:\n"
        "  - match: write_file(src/**)\n"
        "    action: deny\n"
        "  - match: write_file(src/*.py)\n"
        "    action: allow\n",
        encoding="utf-8",
    )
    loader = RuleLoader(RulePaths(tmp_path / "u", tmp_path / "p", local))
    assert loader.query("write_file", "src/a.py").action is PermissionAction.ALLOW


def test_cross_layer_effective_deny_wins(tmp_path: Path) -> None:
    user = tmp_path / "user.yml"
    local = tmp_path / "local.yml"
    user.write_text("rules:\n- match: read_file(**)\n  action: deny\n", encoding="utf-8")
    local.write_text("rules:\n- match: read_file(**)\n  action: allow\n", encoding="utf-8")
    loader = RuleLoader(RulePaths(user, tmp_path / "p", local))
    assert loader.query("read_file", "a.txt").action is PermissionAction.DENY


def test_invalid_existing_file_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "bad.yml"
    path.write_text("rules: nope\n", encoding="utf-8")
    with pytest.raises(PermissionRuleError, match="rules 必须是列表"):
        RuleLoader(RulePaths(path, tmp_path / "p", tmp_path / "l")).validate_all()
