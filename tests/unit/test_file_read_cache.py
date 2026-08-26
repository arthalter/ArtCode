from __future__ import annotations

from pathlib import Path

from artcode.tools.file_cache import FileReadCache


def test_cache_hits_after_put_and_misses_for_other_paths(tmp_path: Path) -> None:
    cache = FileReadCache()
    target = tmp_path / "a.txt"
    target.write_text("hello", encoding="utf-8")

    assert cache.get(target) is None
    cache.put(target, "hello")

    assert cache.get(target) == "hello"
    assert cache.get(tmp_path / "missing.txt") is None
    assert tmp_path / "a.txt" in cache


def test_cache_key_is_normalized_absolute_path(tmp_path: Path) -> None:
    cache = FileReadCache()
    target = tmp_path / "sub" / "b.txt"
    target.parent.mkdir()
    target.write_text("x", encoding="utf-8")
    cache.put(target, "x")

    # A different spelling of the same file hits the same entry.
    assert cache.get(Path(tmp_path) / "sub" / ".." / "sub" / "b.txt") == "x"


def test_modified_file_invalidates_entry(tmp_path: Path) -> None:
    cache = FileReadCache()
    target = tmp_path / "c.txt"
    target.write_text("old", encoding="utf-8")
    cache.put(target, "old")
    assert cache.get(target) == "old"

    target.write_text("new content", encoding="utf-8")

    assert cache.get(target) is None
    cache.put(target, "new content")
    assert cache.get(target) == "new content"


def test_deleted_file_invalidates_entry(tmp_path: Path) -> None:
    cache = FileReadCache()
    target = tmp_path / "d.txt"
    target.write_text("gone", encoding="utf-8")
    cache.put(target, "gone")

    target.unlink()

    assert cache.get(target) is None


def test_two_worktrees_with_same_relative_path_never_share_entries(
    tmp_path: Path,
) -> None:
    """C10: absolute-path keys isolate identical relative paths."""
    first = tmp_path / "wt-a" / "shared.txt"
    second = tmp_path / "wt-b" / "shared.txt"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_text("alpha", encoding="utf-8")
    second.write_text("beta", encoding="utf-8")
    cache_a = FileReadCache()
    cache_b = FileReadCache()
    cache_a.put(first, "alpha")
    cache_b.put(second, "beta")

    assert cache_a.get(first) == "alpha"
    assert cache_a.get(second) is None
    assert cache_b.get(second) == "beta"
    assert cache_b.get(first) is None
    # Keys are the absolute paths, not the shared relative name.
    assert first.resolve() in cache_a
    assert second.resolve() not in cache_a


def test_max_entries_bounds_memory(tmp_path: Path) -> None:
    cache = FileReadCache(max_entries=2)
    for index in range(5):
        target = tmp_path / f"f{index}.txt"
        target.write_text(str(index), encoding="utf-8")
        cache.put(target, str(index))

    assert cache.size == 2


def test_negative_max_entries_rejected() -> None:
    try:
        FileReadCache(max_entries=0)
    except ValueError:
        return
    raise AssertionError("expected ValueError")
