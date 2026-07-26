from pathlib import Path

from artcode.permissions import PermissionAction, RuleLoader, RulePaths, RuleWriter


def test_writer_updates_duplicate_and_moves_it_to_end(tmp_path: Path) -> None:
    local = tmp_path / "permissions.local.yml"
    local.write_text(
        "rules:\n"
        "- match: read_file(a.txt)\n  action: allow\n"
        "- match: read_file(b.txt)\n  action: allow\n"
        "- match: read_file(a.txt)\n  action: ask\n",
        encoding="utf-8",
    )
    loader = RuleLoader(RulePaths(tmp_path / "u", tmp_path / "p", local))
    RuleWriter(loader).write_exact("read_file(a.txt)", PermissionAction.DENY)
    rules = loader.load_file(local)
    assert [rule.match for rule in rules] == ["read_file(b.txt)", "read_file(a.txt)"]
    assert rules[-1].action is PermissionAction.DENY
