from __future__ import annotations

from pathlib import Path
import re
import string
import tempfile

from hypothesis import given, settings, strategies as st

from artcode.worktrees.naming import validate_worktree_name


_SEGMENT_PATTERN = re.compile(r"[a-z0-9][a-z0-9._-]{0,31}")
_SAFE_SEGMENT = st.text(
    alphabet=string.ascii_lowercase + string.digits + "._-",
    min_size=1,
    max_size=32,
).filter(lambda value: _SEGMENT_PATTERN.fullmatch(value) is not None)
_SHORT_SEGMENT_LIST = st.lists(_SAFE_SEGMENT, min_size=1, max_size=6).filter(
    lambda parts: len("/".join(parts).encode("utf-8")) <= 64
)


def _names() -> st.SearchStrategy[str]:
    return st.one_of(
        st.text(alphabet=string.ascii_letters + string.digits + string.punctuation + " \t\n", max_size=80),
        st.text(alphabet="\x00\x01\x1f\x7f\\/~.", max_size=40),
        st.lists(_SAFE_SEGMENT, min_size=1, max_size=6).map("/".join),
        st.just("agent-01234567"),
        st.just(".."),
        st.just("."),
        st.just(""),
    )


@settings(max_examples=300, deadline=None)
@given(name=_names())
def test_validated_names_never_escape_managed_root(name: str) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary) / "managed"
        root.mkdir()
        sentinel = Path(temporary) / "sentinel.txt"
        sentinel.write_text("keep", encoding="utf-8")

        try:
            selected = validate_worktree_name(root, name)
        except ValueError:
            return

        resolved = selected.path.resolve(strict=False)
        root_resolved = root.resolve(strict=False)
        assert resolved != root_resolved
        assert root_resolved in resolved.parents
        assert not resolved.exists() or resolved.is_relative_to(root)
        assert sentinel.read_text(encoding="utf-8") == "keep"
        # Branch names must never be usable for git parameter injection.
        assert "\n" not in selected.branch and "\r" not in selected.branch
        assert selected.branch.startswith("worktree-")


@settings(max_examples=200, deadline=None)
@given(segments=_SHORT_SEGMENT_LIST)
def test_nested_valid_names_keep_segments_and_stay_inside_root(segments: list[str]) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary) / "managed"
        root.mkdir()
        name = "/".join(segments)

        selected = validate_worktree_name(root, name)

        assert selected.value == name
        assert selected.path == root.joinpath(*segments)
        assert root.resolve(strict=False) in selected.path.resolve(strict=False).parents
        assert selected.branch == f"worktree-{name}"


@settings(max_examples=200, deadline=None)
@given(name=st.text(alphabet=string.printable, max_size=200))
def test_system_names_require_agent_prefix(name: str) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary) / "managed"
        root.mkdir()
        try:
            selected = validate_worktree_name(root, name, system=True)
        except ValueError:
            return
        assert selected.value.startswith("agent-")
