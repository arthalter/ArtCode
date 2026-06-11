from __future__ import annotations

from pathlib import Path

import pytest

from artcode.tools.policy import AllowedPathPolicy


def policy_for(root: Path) -> AllowedPathPolicy:
    root.mkdir()
    return AllowedPathPolicy((root,))


def test_allowed_path_inside_root_resolves(tmp_path) -> None:
    policy = policy_for(tmp_path / "sandbox")
    file_path = tmp_path / "sandbox" / "note.txt"
    file_path.write_text("hello", encoding="utf-8")

    assert policy.resolve_existing_path("note.txt") == file_path.resolve()


def test_absolute_path_outside_root_is_rejected(tmp_path) -> None:
    policy = policy_for(tmp_path / "sandbox")
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")

    with pytest.raises(ValueError, match="不在允许目录"):
        policy.resolve_existing_path(str(outside))


def test_parent_traversal_outside_root_is_rejected(tmp_path) -> None:
    policy = policy_for(tmp_path / "sandbox")
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")

    with pytest.raises(ValueError, match="不在允许目录"):
        policy.resolve_existing_path("../outside.txt")


def test_new_file_parent_must_be_inside_root(tmp_path) -> None:
    policy = policy_for(tmp_path / "sandbox")

    with pytest.raises(ValueError, match="不在允许目录"):
        policy.resolve_new_file_path("../outside.txt")


def test_new_file_inside_root_resolves_parent(tmp_path) -> None:
    policy = policy_for(tmp_path / "sandbox")

    resolved = policy.resolve_new_file_path("nested/new.txt")

    assert resolved == (tmp_path / "sandbox" / "nested" / "new.txt").resolve()
