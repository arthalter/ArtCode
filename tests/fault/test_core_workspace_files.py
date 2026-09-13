from __future__ import annotations

import os
from pathlib import Path

import pytest

from artcode._workspace import LocalWorkspace
from artcode.core.workspace import AtomicWriteFailure, TargetChanged


def test_atomic_replace_failure_keeps_original_and_removes_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    target_path = root / "note.txt"
    target_path.write_text("original", encoding="utf-8")
    scope = LocalWorkspace(root)
    target = scope.prepare_target("note.txt", must_exist=True)

    def fail_replace(*args, **kwargs):
        raise OSError("injected replace failure")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(AtomicWriteFailure):
        scope.write_text(target, "new", overwrite=True)

    assert target_path.read_text(encoding="utf-8") == "original"
    assert list(root.glob(".note.txt.artcode-*.tmp")) == []


def test_parent_replaced_with_symlink_after_prepare_cannot_write_outside(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    outside = tmp_path / "outside"
    parent = root / "nested"
    parent.mkdir(parents=True)
    outside.mkdir()
    scope = LocalWorkspace(root)
    target = scope.prepare_target("nested/note.txt", must_exist=False)
    parent.rmdir()
    parent.symlink_to(outside, target_is_directory=True)

    with pytest.raises(TargetChanged):
        scope.write_text(target, "escape", overwrite=False)
    assert not (outside / "note.txt").exists()


def test_invalid_utf8_read_is_explicit_and_does_not_change_file(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    target_path = root / "binary.dat"
    target_path.write_bytes(b"\xff\xfe")
    scope = LocalWorkspace(root)

    with pytest.raises(UnicodeDecodeError):
        scope.read_text(scope.prepare_target("binary.dat", must_exist=True))
    assert target_path.read_bytes() == b"\xff\xfe"


def test_result_store_replace_failure_leaves_no_partial_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    scope = LocalWorkspace(root)

    def fail_replace(*args, **kwargs):
        raise OSError("injected result replace failure")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(AtomicWriteFailure):
        scope.store_result("call", "complete result")

    result_root = root / ".artcode" / "results" / scope.scope_id
    assert list(result_root.glob("*")) == []
