from __future__ import annotations

from pathlib import Path

from artcode._workspace import LocalWorkspace


def test_two_scopes_with_same_relative_path_never_share_cache_or_effects(tmp_path: Path) -> None:
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()
    first = LocalWorkspace(first_root)
    second = LocalWorkspace(second_root)

    first.write_text(first.prepare_target("same.txt", must_exist=False), "one", overwrite=False)
    second.write_text(second.prepare_target("same.txt", must_exist=False), "two", overwrite=False)

    assert first.read_text(first.prepare_target("same.txt", must_exist=True)).text == "one"
    assert second.read_text(second.prepare_target("same.txt", must_exist=True)).text == "two"


def test_prepare_read_edit_search_and_result_round_trip(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    scope = LocalWorkspace(root, result_preview_bytes=8)

    created = scope.write_text(
        scope.prepare_target("src/main.py", must_exist=False),
        "value = 'before'\n",
        overwrite=False,
    )
    scope.edit_text(
        scope.prepare_target(created.path, must_exist=True),
        "before",
        "after",
    )
    matches = scope.search_text("after", glob="**/*.py", limit=10)
    stored = scope.store_result("search-1", "\n".join(match.text for match in matches.matches))
    restored = scope.read_result(stored.reference, start_line=1, end_line=1)

    assert created.path == "src/main.py"
    assert matches.matches[0].path == "src/main.py"
    assert restored.text == "value = 'after'"
