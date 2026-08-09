from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
import yaml
from hypothesis import given, settings, strategies as st

from artcode.permissions import PermissionAction, PermissionRule, RuleLoader, RulePaths, RuleWriter
from artcode.permissions.service import exact_match

pytestmark = [pytest.mark.ch10_5, pytest.mark.property]

TARGETS = st.text(
    alphabet=st.characters(
        blacklist_categories=("Cs", "Cc"),
        blacklist_characters=("\x00", "\n", "\r"),
    ),
    min_size=1,
    max_size=60,
).filter(lambda value: bool(value.strip()))


@pytest.mark.parametrize(
    ("tool_name", "path_mode"),
    [("custom_path", True), ("run_command", False)],
    ids=("path-literals", "command-literals"),
)
@given(target=TARGETS)
@settings(max_examples=80)
def test_exact_rule_escaping_round_trips_arbitrary_literal_target(
    tool_name: str,
    path_mode: bool,
    target: str,
) -> None:
    selected = target if path_mode else target.strip()
    rule = PermissionRule.parse(
        exact_match(tool_name, selected),
        PermissionAction.ALLOW.value,
        {tool_name},
    )

    assert rule.matches(tool_name, target)
    assert not rule.matches("different", target)


@given(
    user=st.sampled_from(tuple(PermissionAction)[:-1]),
    project=st.sampled_from(tuple(PermissionAction)[:-1]),
    local=st.sampled_from(tuple(PermissionAction)[:-1]),
)
@settings(max_examples=40)
def test_rule_layer_priority_is_deterministic(
    user: PermissionAction,
    project: PermissionAction,
    local: PermissionAction,
) -> None:
    with TemporaryDirectory() as raw_directory:
        root = Path(raw_directory)
        paths = RulePaths(root / "user.yml", root / "project.yml", root / "local.yml")
        for path, action in zip((paths.user, paths.project, paths.local), (user, project, local)):
            path.write_text(
                yaml.safe_dump({"rules": [{"match": "custom(**)", "action": action.value}]}),
                encoding="utf-8",
            )
        loader = RuleLoader(paths, allowed_tool_names={"custom"})
        match = loader.query("custom", "a/b.txt")

    expected = next(
        (action for action in (user, project, local) if action is PermissionAction.DENY),
        local,
    )
    assert match.action is expected


@given(target=TARGETS, action=st.sampled_from((PermissionAction.ALLOW, PermissionAction.DENY)))
@settings(max_examples=50)
def test_rule_writer_persists_and_reloads_exact_literal(
    target: str,
    action: PermissionAction,
) -> None:
    with TemporaryDirectory() as raw_directory:
        root = Path(raw_directory)
        paths = RulePaths(root / "user.yml", root / "project.yml", root / "local.yml")
        loader = RuleLoader(paths, allowed_tool_names={"custom"})

        RuleWriter(loader).write_exact(exact_match("custom", target), action)

        reloaded = RuleLoader(paths, allowed_tool_names={"custom"}).query("custom", target)
        assert reloaded is not None
        assert reloaded.action is action
