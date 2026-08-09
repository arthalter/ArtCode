from __future__ import annotations

from pathlib import Path

import pytest

from artcode.tools import (
    AtomicWriteError,
    SensitivePathError,
    TargetChangedError,
    WorkspaceBoundaryError,
    WorkspaceFileAccess,
    WorkspaceFileError,
    WorkspacePathPolicy,
)
from artcode.workspace import Workspace

pytestmark = pytest.mark.ch10_5


def access_for(root: Path, *sensitive: Path) -> WorkspaceFileAccess:
    return WorkspaceFileAccess(
        WorkspacePathPolicy(Workspace.from_path(root), tuple(sensitive))
    )


@pytest.mark.parametrize(
    "raw",
    ["note.txt", "./note.txt", "sub/../note.txt", "ABSOLUTE", "你好.txt", "space name.txt"],
    ids=("relative", "dot", "normalized", "absolute", "unicode", "space"),
)
def test_prepare_existing_accepts_safe_path_forms(tmp_path, raw) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    name = "你好.txt" if raw == "你好.txt" else "space name.txt" if raw == "space name.txt" else "note.txt"
    target = root / name
    target.write_text("ok", encoding="utf-8")
    if raw == "sub/../note.txt":
        (root / "sub").mkdir()
    selected = str(target) if raw == "ABSOLUTE" else raw

    snapshot = access_for(root).prepare_existing(selected, root)

    assert snapshot.approved_path == target
    assert snapshot.target_identity is not None


@pytest.mark.parametrize("raw", [None, 1, "", "   "], ids=("none", "integer", "empty", "blank"))
def test_prepare_rejects_invalid_raw_path(tmp_path, raw) -> None:
    root = tmp_path / "workspace"
    root.mkdir()

    with pytest.raises(WorkspaceFileError):
        access_for(root).prepare_file(raw, root)


@pytest.mark.parametrize(
    "scenario",
    ["parent", "absolute", "file-symlink", "directory-symlink"],
    ids=("parent", "absolute", "file-symlink", "directory-symlink"),
)
def test_prepare_rejects_workspace_escape(tmp_path, scenario) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret", encoding="utf-8")
    if scenario == "parent":
        raw = "../outside/secret.txt"
    elif scenario == "absolute":
        raw = str(outside / "secret.txt")
    elif scenario == "file-symlink":
        (root / "link.txt").symlink_to(outside / "secret.txt")
        raw = "link.txt"
    else:
        (root / "link").symlink_to(outside, target_is_directory=True)
        raw = "link/secret.txt"

    with pytest.raises(WorkspaceBoundaryError):
        access_for(root).prepare_existing(raw, root)


@pytest.mark.parametrize(
    "scenario",
    ["exact", "child", "file-symlink", "new-child"],
    ids=("exact", "child", "file-symlink", "new-child"),
)
def test_prepare_rejects_sensitive_target(tmp_path, scenario) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    sensitive = root / ".artcode"
    sensitive.mkdir()
    (sensitive / "secret.txt").write_text("secret", encoding="utf-8")
    if scenario == "exact":
        raw, existing = ".artcode", True
    elif scenario == "child":
        raw, existing = ".artcode/secret.txt", True
    elif scenario == "file-symlink":
        (root / "link.txt").symlink_to(sensitive / "secret.txt")
        raw, existing = "link.txt", True
    else:
        raw, existing = ".artcode/new/secret.txt", False
    access = access_for(root, sensitive)

    with pytest.raises(SensitivePathError):
        (access.prepare_existing if existing else access.prepare_file)(raw, root)


@pytest.mark.parametrize(
    "scenario",
    ["file", "directory", "new-child", "display"],
    ids=("file", "directory", "new-child", "display"),
)
def test_internal_symlink_resolves_to_real_workspace_target(tmp_path, scenario) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    actual = root / "actual"
    actual.mkdir()
    (actual / "note.txt").write_text("ok", encoding="utf-8")
    (root / "link").symlink_to(actual, target_is_directory=True)
    access = access_for(root)
    if scenario == "file":
        snapshot = access.prepare_existing("link/note.txt", root)
        expected = actual / "note.txt"
    elif scenario == "directory":
        snapshot = access.prepare_existing("link", root)
        expected = actual
    else:
        snapshot = access.prepare_file("link/new/note.txt", root)
        expected = actual / "new" / "note.txt"

    assert snapshot.approved_path == expected
    if scenario == "display":
        assert snapshot.display_target == "actual/new/note.txt"


@pytest.mark.parametrize(
    "raw",
    ["new.txt", "a/new.txt", "a/b/new.txt", "你好/文件.txt", "a/../new.txt", "ABSOLUTE"],
    ids=("file", "one-parent", "two-parents", "unicode", "normalized", "absolute"),
)
def test_prepare_new_file_allows_missing_internal_parents(tmp_path, raw) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    selected = str(root / "absolute" / "new.txt") if raw == "ABSOLUTE" else raw

    snapshot = access_for(root).prepare_file(selected, root)

    assert snapshot.root == root
    assert root == snapshot.approved_path or root in snapshot.approved_path.parents
    assert snapshot.target_identity is None


@pytest.mark.parametrize(
    "scenario",
    [
        "unchanged",
        "file-replaced",
        "file-deleted",
        "link-retarget-internal",
        "link-retarget-outside",
        "directory-link-retarget",
        "new-target-created",
        "new-parent-linked-outside",
    ],
    ids=("unchanged", "file-replaced", "file-deleted", "link-internal", "link-outside", "directory-link", "new-created", "new-parent-link"),
)
def test_verify_detects_target_semantic_change(tmp_path, scenario) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    first = root / "first.txt"
    second = root / "second.txt"
    outside_file = outside / "outside.txt"
    for path, text in ((first, "first"), (second, "second"), (outside_file, "outside")):
        path.write_text(text, encoding="utf-8")
    access = access_for(root)
    if scenario in {"link-retarget-internal", "link-retarget-outside"}:
        link = root / "link.txt"
        link.symlink_to(first)
        snapshot = access.prepare_existing("link.txt", root)
        link.unlink()
        link.symlink_to(second if scenario.endswith("internal") else outside_file)
    elif scenario == "directory-link-retarget":
        one = root / "one"
        two = root / "two"
        one.mkdir()
        two.mkdir()
        (one / "note.txt").write_text("one", encoding="utf-8")
        (two / "note.txt").write_text("two", encoding="utf-8")
        link = root / "dir"
        link.symlink_to(one, target_is_directory=True)
        snapshot = access.prepare_existing("dir/note.txt", root)
        link.unlink()
        link.symlink_to(two, target_is_directory=True)
    elif scenario in {"new-target-created", "new-parent-linked-outside"}:
        snapshot = access.prepare_file("new/note.txt", root)
        if scenario == "new-target-created":
            (root / "new").mkdir()
            (root / "new" / "note.txt").write_text("appeared", encoding="utf-8")
        else:
            (root / "new").symlink_to(outside, target_is_directory=True)
    else:
        snapshot = access.prepare_existing("first.txt", root)
        if scenario == "file-replaced":
            first.unlink()
            first.write_text("replacement", encoding="utf-8")
        elif scenario == "file-deleted":
            first.unlink()

    if scenario == "unchanged":
        assert access.verify(snapshot) == first
    else:
        with pytest.raises(TargetChangedError):
            access.verify(snapshot)


@pytest.mark.parametrize(
    "scenario",
    ["utf8", "unicode", "internal-link", "invalid-utf8", "changed", "directory"],
    ids=("utf8", "unicode", "internal-link", "invalid-utf8", "changed", "directory"),
)
def test_read_text_uses_verified_file_descriptor(tmp_path, scenario) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "note.txt"
    content = "你好" if scenario == "unicode" else "hello"
    if scenario == "invalid-utf8":
        target.write_bytes(b"\xff")
    else:
        target.write_text(content, encoding="utf-8")
    raw = "note.txt"
    if scenario == "internal-link":
        link = root / "link.txt"
        link.symlink_to(target)
        raw = "link.txt"
    elif scenario == "directory":
        raw = "."
    access = access_for(root)
    snapshot = access.prepare_existing(raw, root)
    if scenario == "changed":
        target.unlink()
        target.write_text("changed", encoding="utf-8")

    if scenario == "invalid-utf8":
        with pytest.raises(UnicodeDecodeError):
            access.read_text(snapshot)
    elif scenario == "changed":
        with pytest.raises(TargetChangedError):
            access.read_text(snapshot)
    elif scenario == "directory":
        with pytest.raises(OSError):
            access.read_text(snapshot)
    else:
        assert access.read_text(snapshot) == content


@pytest.mark.parametrize(
    "scenario",
    ["new", "nested", "overwrite", "deny-overwrite", "unicode", "internal-link", "empty", "large"],
    ids=("new", "nested", "overwrite", "deny-overwrite", "unicode", "internal-link", "empty", "large"),
)
def test_atomic_write_commits_complete_content(tmp_path, scenario) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    access = access_for(root)
    raw = "note.txt"
    overwrite = False
    content = ""
    if scenario == "nested":
        raw = "a/b/note.txt"
    elif scenario in {"overwrite", "deny-overwrite"}:
        (root / raw).write_text("old", encoding="utf-8")
        overwrite = scenario == "overwrite"
        content = "new"
    elif scenario == "unicode":
        raw, content = "目录/文件.txt", "你好"
    elif scenario == "internal-link":
        actual = root / "actual"
        actual.mkdir()
        (root / "link").symlink_to(actual, target_is_directory=True)
        raw, content = "link/note.txt", "linked"
    elif scenario == "large":
        content = "x" * 100_000
    else:
        content = "value" if scenario == "new" else ""
    snapshot = access.prepare_file(raw, root)

    if scenario == "deny-overwrite":
        with pytest.raises(FileExistsError):
            access.atomic_write_text(snapshot, content, overwrite=False)
        assert (root / raw).read_text(encoding="utf-8") == "old"
    else:
        path = access.atomic_write_text(snapshot, content, overwrite=overwrite)
        assert path.read_text(encoding="utf-8") == content
        assert not list(path.parent.glob(f".{path.name}.artcode-*.tmp"))


@pytest.mark.parametrize(
    "scenario",
    ["find-recursive", "find-extension", "find-absolute", "find-outside", "find-sensitive", "search-all", "search-file", "search-directory", "search-changed"],
    ids=("find-recursive", "find-extension", "find-absolute", "find-outside", "find-sensitive", "search-all", "search-file", "search-directory", "search-changed"),
)
def test_discovery_only_returns_current_safe_files(tmp_path, scenario) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    sub = root / "sub"
    sub.mkdir()
    a = root / "a.txt"
    b = sub / "b.py"
    a.write_text("a", encoding="utf-8")
    b.write_text("b", encoding="utf-8")
    sensitive = root / ".artcode"
    sensitive.mkdir()
    secret = sensitive / "secret.txt"
    secret.write_text("secret", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    access = access_for(root, sensitive)
    if scenario.startswith("find"):
        pattern = {
            "find-recursive": "**/*",
            "find-extension": "**/*.py",
            "find-absolute": str(a),
            "find-outside": str(outside),
            "find-sensitive": "**/*.txt",
        }[scenario]
        files = access.find_files(pattern)
        if scenario == "find-extension":
            assert files == [b]
        elif scenario == "find-absolute":
            assert files == [a]
        elif scenario == "find-outside":
            assert files == []
        elif scenario == "find-sensitive":
            assert a in files and secret not in files
        else:
            assert set(files) == {a, b}
        return
    target = None
    if scenario == "search-file":
        target = access.prepare_existing("a.txt", root)
    elif scenario in {"search-directory", "search-changed"}:
        target = access.prepare_existing("sub", root)
    if scenario == "search-changed":
        sub.rename(root / "old-sub")
        with pytest.raises(TargetChangedError):
            access.search_files(target)
    else:
        files = access.search_files(target)
        expected = {a} if scenario == "search-file" else {b} if scenario == "search-directory" else {a, b}
        assert set(files) == expected


def test_constructor_rejects_empty_root_policy() -> None:
    class EmptyPolicy:
        allowed_roots = ()

    with pytest.raises(ValueError, match="at least one root"):
        WorkspaceFileAccess(EmptyPolicy())


def test_read_text_rechecks_descriptor_identity(tmp_path, monkeypatch) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "note.txt"
    target.write_text("old", encoding="utf-8")
    access = access_for(root)
    snapshot = access.prepare_existing("note.txt", root)
    target.unlink()
    target.write_text("new", encoding="utf-8")
    monkeypatch.setattr(access, "verify", lambda selected: selected.approved_path)

    with pytest.raises(TargetChangedError, match="读取前"):
        access.read_text(snapshot)


def test_atomic_write_detects_races_after_verification(tmp_path, monkeypatch) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "note.txt"
    access = access_for(root)
    snapshot = access.prepare_file("note.txt", root)
    original_verify = access.verify
    calls = 0

    def create_between_checks(selected):
        nonlocal calls
        calls += 1
        path = original_verify(selected) if calls == 1 else selected.approved_path
        if calls == 2:
            target.write_text("appeared", encoding="utf-8")
        return path

    monkeypatch.setattr(access, "verify", create_between_checks)
    with pytest.raises(TargetChangedError, match="写入前"):
        access.atomic_write_text(snapshot, "new", overwrite=True)


def test_atomic_write_rejects_symlink_race(tmp_path, monkeypatch) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "note.txt"
    target.write_text("old", encoding="utf-8")
    alternate = root / "alternate.txt"
    alternate.write_text("alternate", encoding="utf-8")
    access = access_for(root)
    snapshot = access.prepare_existing("note.txt", root)
    monkeypatch.setattr(access, "verify", lambda selected: selected.approved_path)
    monkeypatch.setattr(access, "_entry_identity", lambda parent, name: snapshot.target_identity)
    target.unlink()
    target.symlink_to(alternate)

    with pytest.raises(TargetChangedError, match="符号链接"):
        access.atomic_write_text(snapshot, "new", overwrite=True)


def test_atomic_write_maps_os_error_and_cleans_temp(tmp_path, monkeypatch) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    access = access_for(root)
    snapshot = access.prepare_file("note.txt", root)

    def fail_replace(*args, **kwargs):
        raise OSError("disk failure")

    monkeypatch.setattr("artcode.tools.filesystem.os.replace", fail_replace)
    with pytest.raises(AtomicWriteError, match="原子写入失败"):
        access.atomic_write_text(snapshot, "content", overwrite=False)
    assert not list(root.glob(".note.txt.artcode-*.tmp"))


def test_snapshot_maps_stat_failure(tmp_path, monkeypatch) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    access = access_for(root)
    target = root / "note.txt"
    original_stat = Path.stat

    def fail_target_stat(self, *args, **kwargs):
        if self == target:
            raise OSError("stat failed")
        return original_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", fail_target_stat)
    with pytest.raises(WorkspaceFileError, match="无法读取目标状态"):
        access.prepare_file("note.txt", root)


def test_open_parent_rejects_root_and_outside_targets(tmp_path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    access = access_for(root)
    with pytest.raises(WorkspaceFileError, match="必须是"):
        access._open_parent(root, root, create=False)
    with pytest.raises(WorkspaceBoundaryError):
        access._open_parent(root, tmp_path / "outside.txt", create=False)


def test_open_parent_missing_and_changed_components_close_descriptors(tmp_path, monkeypatch) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    access = access_for(root)
    with pytest.raises(FileNotFoundError):
        access._open_parent(root, root / "missing" / "note.txt", create=False)

    (root / "component").write_text("not a directory", encoding="utf-8")
    with pytest.raises(TargetChangedError, match="目录目标"):
        access._open_parent(root, root / "component" / "note.txt", create=False)


def test_open_parent_propagates_unclassified_os_error(tmp_path, monkeypatch) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "component").mkdir()
    access = access_for(root)
    original_open = __import__("os").open

    def fail_component(path, flags, *args, **kwargs):
        if path == "component":
            raise OSError(5, "io error")
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr("artcode.tools.filesystem.os.open", fail_component)
    with pytest.raises(OSError, match="io error"):
        access._open_parent(root, root / "component" / "note.txt", create=False)
