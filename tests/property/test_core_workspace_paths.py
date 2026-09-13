from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from hypothesis import given, settings, strategies as st
import pytest

from artcode._workspace import LocalWorkspace
from artcode.core.workspace import PathOutsideWorkspace


SEGMENT = st.text(
    alphabet=st.sampled_from(list("abcdefghijklmnopqrstuvwxyz0123456789-_ 空你我")),
    min_size=1,
    max_size=10,
).filter(lambda value: value == value.strip() and value not in {".", ".."})
CONTENT = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",), blacklist_characters=("\x00",)),
    max_size=300,
)


@given(parts=st.lists(SEGMENT, min_size=0, max_size=4), content=CONTENT)
@settings(max_examples=50)
def test_unicode_content_round_trips_inside_explicit_scope(parts: list[str], content: str) -> None:
    with TemporaryDirectory() as raw:
        root = Path(raw) / "scope"
        root.mkdir()
        scope = LocalWorkspace(root)
        relative = "/".join([*parts, "结果.txt"])

        change = scope.write_text(scope.prepare_target(relative, must_exist=False), content, overwrite=False)

        assert change.path == relative
        assert (root / relative).read_bytes() == content.encode("utf-8")


@given(depth=st.integers(min_value=1, max_value=8), name=SEGMENT)
@settings(max_examples=50)
def test_parent_traversal_never_escapes_scope(depth: int, name: str) -> None:
    with TemporaryDirectory() as raw:
        root = Path(raw) / "scope"
        root.mkdir()
        scope = LocalWorkspace(root)

        with pytest.raises(PathOutsideWorkspace):
            scope.prepare_target("/".join([*(".." for _ in range(depth)), name]), must_exist=False)


@given(parts=st.lists(SEGMENT, min_size=1, max_size=4))
@settings(max_examples=40)
def test_every_sensitive_descendant_is_rejected(parts: list[str]) -> None:
    with TemporaryDirectory() as raw:
        root = Path(raw) / "scope"
        sensitive = root / ".private"
        sensitive.mkdir(parents=True)
        scope = LocalWorkspace(root, sensitive_paths=(sensitive,))

        with pytest.raises(Exception) as caught:
            scope.prepare_target("/".join([".private", *parts]), must_exist=False)
        assert caught.type.__name__ == "SensitivePath"
