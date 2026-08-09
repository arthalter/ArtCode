from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from hypothesis import given, settings, strategies as st

from artcode.tools import (
    SensitivePathError,
    WorkspaceBoundaryError,
    WorkspaceFileAccess,
    WorkspacePathPolicy,
)
from artcode.workspace import Workspace

pytestmark = [pytest.mark.ch10_5, pytest.mark.property]

SEGMENT = st.text(
    alphabet=st.sampled_from(list("abcdefghijklmnopqrstuvwxyz0123456789-_ 空你我")),
    min_size=1,
    max_size=12,
).filter(lambda value: value == value.strip() and value not in {"", ".", ".."})
CONTENT = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",), blacklist_characters=("\x00",)),
    max_size=500,
)


def access_for(root: Path, *sensitive: Path) -> WorkspaceFileAccess:
    return WorkspaceFileAccess(
        WorkspacePathPolicy(Workspace.from_path(root), tuple(sensitive))
    )


@given(parts=st.lists(SEGMENT, min_size=1, max_size=5, unique=False))
@settings(max_examples=60)
def test_safe_relative_components_resolve_inside_workspace(parts: list[str]) -> None:
    with TemporaryDirectory() as raw:
        root = Path(raw) / "workspace"
        root.mkdir()
        root = root.resolve()
        snapshot = access_for(root).prepare_file("/".join([*parts, "note.txt"]), root)

        assert root in snapshot.approved_path.parents


@given(parts=st.lists(SEGMENT, min_size=0, max_size=4), content=CONTENT)
@settings(max_examples=50)
def test_arbitrary_unicode_content_round_trips_atomically(parts: list[str], content: str) -> None:
    with TemporaryDirectory() as raw:
        root = Path(raw) / "workspace"
        root.mkdir()
        root = root.resolve()
        relative = "/".join([*parts, "结果.txt"])
        access = access_for(root)
        snapshot = access.prepare_file(relative, root)

        path = access.atomic_write_text(snapshot, content, overwrite=False)

        assert path.read_bytes() == content.encode("utf-8")
        assert root in path.parents


@given(depth=st.integers(min_value=1, max_value=8), name=SEGMENT)
@settings(max_examples=40)
def test_parent_traversal_never_escapes_workspace(depth: int, name: str) -> None:
    with TemporaryDirectory() as raw:
        root = Path(raw) / "workspace"
        root.mkdir()
        root = root.resolve()
        relative = "/".join([*(".." for _ in range(depth)), name, "note.txt"])

        with pytest.raises(WorkspaceBoundaryError):
            access_for(root).prepare_file(relative, root)


@given(directory=SEGMENT, child=SEGMENT, content=CONTENT)
@settings(max_examples=40)
def test_internal_symlink_writes_only_to_resolved_internal_target(
    directory: str,
    child: str,
    content: str,
) -> None:
    with TemporaryDirectory() as raw:
        root = Path(raw) / "workspace"
        root.mkdir()
        root = root.resolve()
        actual = root / "actual"
        actual.mkdir()
        link = root / directory
        if link == actual:
            return
        link.symlink_to(actual, target_is_directory=True)
        access = access_for(root)
        snapshot = access.prepare_file(f"{directory}/{child}.txt", root)

        path = access.atomic_write_text(snapshot, content, overwrite=False)

        assert path == actual / f"{child}.txt"
        assert path.read_bytes() == content.encode("utf-8")


@given(parts=st.lists(SEGMENT, min_size=1, max_size=4))
@settings(max_examples=40)
def test_every_sensitive_descendant_is_rejected(parts: list[str]) -> None:
    with TemporaryDirectory() as raw:
        root = Path(raw) / "workspace"
        root.mkdir()
        root = root.resolve()
        sensitive = root / ".artcode"
        sensitive.mkdir()
        relative = "/".join([".artcode", *parts, "secret.txt"])

        with pytest.raises(SensitivePathError):
            access_for(root, sensitive).prepare_file(relative, root)
