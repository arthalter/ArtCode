from __future__ import annotations

from pathlib import Path

import pytest

from artcode._workspace import LocalWorkspace
from artcode.core.workspace import (
    AtomicWriteFailure,
    PathOutsideWorkspace,
    SensitivePath,
    TargetChanged,
)


def workspace(
    root: Path,
    *,
    sensitive: tuple[Path, ...] = (),
    **limits: int,
) -> LocalWorkspace:
    root.mkdir(parents=True, exist_ok=True)
    return LocalWorkspace(root, sensitive_paths=sensitive, **limits)


def test_scope_requires_an_existing_directory(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="不存在"):
        LocalWorkspace(tmp_path / "missing")

    file_path = tmp_path / "file"
    file_path.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="不是目录"):
        LocalWorkspace(file_path)


def test_prepare_rejects_outside_and_sensitive_targets(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    secret = root / ".secrets"
    secret.mkdir(parents=True)
    scope = workspace(root, sensitive=(secret,))

    with pytest.raises(PathOutsideWorkspace):
        scope.prepare_target("../outside.txt", must_exist=False)
    with pytest.raises(SensitivePath):
        scope.prepare_target(".secrets/key", must_exist=False)


def test_read_text_supports_bounded_line_ranges(tmp_path: Path) -> None:
    scope = workspace(tmp_path / "workspace")
    target = scope.root / "notes.txt"
    target.write_text("one\ntwo\nthree\n", encoding="utf-8")

    result = scope.read_text(scope.prepare_target("notes.txt", must_exist=True), start_line=2, end_line=2)

    assert result.text == "two\n"
    assert result.start_line == 2
    assert result.end_line == 2
    assert result.total_lines == 3
    assert result.truncated is False


def test_read_text_reports_bounded_preview_for_large_file(tmp_path: Path) -> None:
    scope = workspace(tmp_path / "workspace", read_char_limit=32)
    (scope.root / "large.txt").write_text("x" * 80 + "\n", encoding="utf-8")

    result = scope.read_text(scope.prepare_target("large.txt", must_exist=True))

    assert len(result.text) == 32
    assert result.truncated is True
    assert result.next_line == 1


def test_create_builds_missing_parents_and_overwrite_requires_intent(tmp_path: Path) -> None:
    scope = workspace(tmp_path / "workspace")
    target = scope.prepare_target("nested/deep/note.txt", must_exist=False)
    created = scope.write_text(target, "first", overwrite=False)

    assert created.created is True
    assert (scope.root / "nested/deep/note.txt").read_text(encoding="utf-8") == "first"

    existing = scope.prepare_target("nested/deep/note.txt", must_exist=False)
    with pytest.raises(FileExistsError):
        scope.write_text(existing, "second", overwrite=False)

    changed = scope.write_text(existing, "second", overwrite=True)
    assert changed.created is False
    assert (scope.root / "nested/deep/note.txt").read_text(encoding="utf-8") == "second"


def test_edit_requires_exactly_one_match_and_never_partially_changes(tmp_path: Path) -> None:
    scope = workspace(tmp_path / "workspace")
    target_path = scope.root / "note.txt"
    target_path.write_text("x x", encoding="utf-8")
    target = scope.prepare_target("note.txt", must_exist=True)

    with pytest.raises(ValueError, match="唯一"):
        scope.edit_text(target, "x", "y")
    assert target_path.read_text(encoding="utf-8") == "x x"

    target_path.write_text("hello world", encoding="utf-8")
    target = scope.prepare_target("note.txt", must_exist=True)
    scope.edit_text(target, "world", "ArtCode")
    assert target_path.read_text(encoding="utf-8") == "hello ArtCode"


def test_prepared_target_is_rechecked_before_effect(tmp_path: Path) -> None:
    scope = workspace(tmp_path / "workspace")
    target_path = scope.root / "note.txt"
    target_path.write_text("old", encoding="utf-8")
    target = scope.prepare_target("note.txt", must_exist=True)
    target_path.unlink()
    target_path.write_text("replacement", encoding="utf-8")

    with pytest.raises(TargetChanged):
        scope.write_text(target, "new", overwrite=True)
    assert target_path.read_text(encoding="utf-8") == "replacement"


def test_internal_symlink_resolves_to_real_target_but_outside_symlink_is_rejected(tmp_path: Path) -> None:
    scope = workspace(tmp_path / "workspace")
    actual = scope.root / "actual"
    actual.mkdir()
    (actual / "note.txt").write_text("inside", encoding="utf-8")
    (scope.root / "inside-link").symlink_to(actual, target_is_directory=True)

    target = scope.prepare_target("inside-link/note.txt", must_exist=True)
    assert target.path == "actual/note.txt"
    assert scope.read_text(target).text == "inside"

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret", encoding="utf-8")
    (scope.root / "outside-link").symlink_to(outside, target_is_directory=True)
    with pytest.raises(PathOutsideWorkspace):
        scope.prepare_target("outside-link/secret.txt", must_exist=True)


def test_missing_target_created_after_prepare_is_not_silently_overwritten(tmp_path: Path) -> None:
    scope = workspace(tmp_path / "workspace")
    target = scope.prepare_target("note.txt", must_exist=False)
    (scope.root / "note.txt").write_text("other writer", encoding="utf-8")

    with pytest.raises(TargetChanged):
        scope.write_text(target, "ours", overwrite=True)
    assert (scope.root / "note.txt").read_text(encoding="utf-8") == "other writer"


def test_find_and_literal_search_are_sorted_bounded_and_utf8_only(tmp_path: Path) -> None:
    scope = workspace(tmp_path / "workspace")
    (scope.root / "b.py").write_text("needle.*\n", encoding="utf-8")
    (scope.root / "a.py").write_text("needle plain\n", encoding="utf-8")
    (scope.root / "binary.py").write_bytes(b"\xff")

    found = scope.find_files("*.py", limit=2)
    searched = scope.search_text("needle.*", glob="*.py", limit=10)

    assert found.paths == ("a.py", "b.py")
    assert found.truncated is True
    assert [(match.path, match.line, match.text) for match in searched.matches] == [
        ("b.py", 1, "needle.*")
    ]
    assert searched.skipped_unreadable == 1


def test_discovery_rejects_absolute_and_parent_patterns(tmp_path: Path) -> None:
    scope = workspace(tmp_path / "workspace")
    with pytest.raises(PathOutsideWorkspace):
        scope.find_files(str(tmp_path / "*.py"))
    with pytest.raises(PathOutsideWorkspace):
        scope.search_text("x", glob="../*.py")


def test_large_result_is_stored_with_bounded_preview_and_explicit_range_read(tmp_path: Path) -> None:
    scope = workspace(tmp_path / "workspace", result_preview_bytes=16, result_read_char_limit=24)
    content = "head\n" + "中" * 40 + "\ntail\n"

    stored = scope.store_result("call/unsafe", content)

    assert stored.original_bytes == len(content.encode("utf-8"))
    assert stored.truncated is True
    assert len(stored.preview.encode("utf-8")) <= 32
    assert stored.reference.startswith("result:")
    assert content not in stored.preview

    first = scope.read_result(stored.reference, start_line=1, end_line=1)
    assert first.text == "head\n"
    with pytest.raises(ValueError, match="范围"):
        scope.read_result(stored.reference)


def test_result_reference_cannot_escape_or_cross_scope(tmp_path: Path) -> None:
    first = workspace(tmp_path / "one")
    second = workspace(tmp_path / "two")
    stored = first.store_result("call", "secret")

    with pytest.raises(ValueError, match="不属于"):
        second.read_result(stored.reference, start_line=1, end_line=1)
    with pytest.raises(ValueError, match="无效"):
        first.read_result("result:../../outside", start_line=1, end_line=1)


def test_scope_close_prevents_further_operations(tmp_path: Path) -> None:
    scope = workspace(tmp_path / "workspace")
    scope.close()
    with pytest.raises(RuntimeError, match="已关闭"):
        scope.find_files("*")
