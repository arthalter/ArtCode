from pathlib import Path

import pytest

from artcode.permissions import PermissionAction, PermissionRuleError
from artcode.permissions.glob import GlobError, glob_match
from artcode.permissions.rules import PermissionRule, RuleLoader, RulePaths, rules_document


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


@pytest.mark.parametrize(
    ("pattern", "value", "path_mode", "matches"),
    [
        (r"literal\*", "literal*", True, True),
        ("src/**/test?.py", "src/unit/test1.py", True, True),
        ("src/**/test?.py", "src/test1.py", True, True),
        ("file[!0-9].txt", "filea.txt", True, True),
        ("file[!0-9].txt", "file1.txt", True, False),
        ("file[abc].txt", "fileb.txt", True, True),
        ("file[.txt", "file[.txt", True, True),
        ("echo *", "echo a/b", False, True),
        ("*.txt", "dir/a.txt", True, False),
    ],
)
def test_glob_language_edges(pattern: str, value: str, path_mode: bool, matches: bool) -> None:
    assert glob_match(pattern, value, path_mode=path_mode) is matches


def test_empty_and_invalid_globs_are_rejected() -> None:
    with pytest.raises(GlobError, match="不能为空"):
        glob_match("", "x", path_mode=True)
    with pytest.raises(GlobError, match="非法 Glob"):
        glob_match("[z-a]", "x", path_mode=True)


@pytest.mark.parametrize(
    ("match", "action", "message"),
    [
        (1, "allow", "match 必须"),
        ("read_file", "allow", "工具名"),
        ("unknown(**)", "allow", "未知工具"),
        ("read_file(**)", "sometimes", "action"),
        ("read_file(**)", "no_match", "不能是 no_match"),
    ],
)
def test_permission_rule_parse_validation(match, action, message) -> None:
    with pytest.raises(ValueError, match=message):
        PermissionRule.parse(match, action)


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("", None),
        ("- item\n", "顶层"),
        ("rules:\n  key: value\n", "rules 必须"),
        ("rules:\n- match: read_file(**)\n", "必须且只能"),
        ("rules:\n- match: bad\n  action: allow\n", "第 1 条规则"),
        ("[broken", "权限规则文件错误"),
    ],
)
def test_rule_loader_validation_matrix(tmp_path: Path, content: str, message: str | None) -> None:
    path = tmp_path / "rules.yml"
    path.write_text(content, encoding="utf-8")
    loader = RuleLoader(RulePaths(path, tmp_path / "p", tmp_path / "l"))
    if message is None:
        assert loader.load_file(path) == []
    else:
        with pytest.raises(PermissionRuleError, match=message):
            loader.load_file(path)


def test_query_no_match_and_rule_document(tmp_path: Path) -> None:
    loader = RuleLoader(RulePaths(tmp_path / "u", tmp_path / "p", tmp_path / "l"))
    assert loader.query("read_file", "none") is None
    rule = PermissionRule.parse("read_file(**)", "ask")
    assert rules_document([rule]) == {"rules": [{"match": "read_file(**)", "action": "ask"}]}
