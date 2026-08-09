from __future__ import annotations

import errno
import os

import pytest

from artcode.tools import (
    AtomicWriteError,
    TargetChangedError,
    WorkspaceFileAccess,
    WorkspacePathPolicy,
)
from artcode.workspace import Workspace

pytestmark = [pytest.mark.ch10_5, pytest.mark.fault]


def access_for(root):
    return WorkspaceFileAccess(WorkspacePathPolicy(Workspace.from_path(root)))


def assert_no_temp(target) -> None:
    assert not list(target.parent.glob(f".{target.name}.artcode-*.tmp"))


def test_replace_failure_keeps_old_file_and_cleans_temp(tmp_path, monkeypatch) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "note.txt"
    target.write_text("old", encoding="utf-8")
    access = access_for(root)
    snapshot = access.prepare_file("note.txt", root)

    def fail_replace(*args, **kwargs):
        raise OSError(errno.EIO, "injected replace failure")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(AtomicWriteError):
        access.atomic_write_text(snapshot, "new", overwrite=True)

    assert target.read_text(encoding="utf-8") == "old"
    assert_no_temp(target)


def test_file_fsync_failure_keeps_old_file_and_cleans_temp(tmp_path, monkeypatch) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "note.txt"
    target.write_text("old", encoding="utf-8")
    access = access_for(root)
    snapshot = access.prepare_file("note.txt", root)

    monkeypatch.setattr(os, "fsync", lambda _fd: (_ for _ in ()).throw(OSError(errno.EIO, "fsync")))
    with pytest.raises(AtomicWriteError):
        access.atomic_write_text(snapshot, "new", overwrite=True)

    assert target.read_text(encoding="utf-8") == "old"
    assert_no_temp(target)


def test_temp_open_failure_leaves_no_file_or_temp(tmp_path, monkeypatch) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "note.txt"
    access = access_for(root)
    snapshot = access.prepare_file("note.txt", root)
    real_open = os.open

    def selective_open(path, *args, **kwargs):
        if isinstance(path, str) and path.startswith(".note.txt.artcode-"):
            raise OSError(errno.EIO, "injected temp open failure")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(os, "open", selective_open)
    with pytest.raises(AtomicWriteError):
        access.atomic_write_text(snapshot, "new", overwrite=False)

    assert not target.exists()
    assert_no_temp(target)


def test_parent_symlink_swap_cannot_create_outside_directory(tmp_path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    access = access_for(root)
    snapshot = access.prepare_file("new/deep/note.txt", root)
    (root / "new").symlink_to(outside, target_is_directory=True)

    with pytest.raises(TargetChangedError):
        access.atomic_write_text(snapshot, "new", overwrite=False)

    assert not (outside / "deep").exists()
    assert not (outside / "note.txt").exists()


def test_target_inode_swap_is_rejected_without_overwriting_replacement(tmp_path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "note.txt"
    target.write_text("approved", encoding="utf-8")
    access = access_for(root)
    snapshot = access.prepare_file("note.txt", root)
    target.unlink()
    target.write_text("replacement", encoding="utf-8")

    with pytest.raises(TargetChangedError):
        access.atomic_write_text(snapshot, "new", overwrite=True)

    assert target.read_text(encoding="utf-8") == "replacement"
    assert_no_temp(target)
