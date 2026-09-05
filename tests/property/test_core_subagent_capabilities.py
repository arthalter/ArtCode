from __future__ import annotations

from hypothesis import given, strategies as st

from artcode._subagent.roles import effective_capabilities
from artcode.core.tool import ToolEffect


NAMES = ("read_file", "find_files", "write_file", "run_command", "agent", "task_cancel")


@given(
    st.sets(st.sampled_from(NAMES)),
    st.sets(st.sampled_from(NAMES)),
    st.sets(st.sampled_from(NAMES)),
)
def test_child_capabilities_never_exceed_parent_role_or_background(
    parent: set[str], role: set[str], background: set[str]
) -> None:
    result = effective_capabilities(
        frozenset(parent), frozenset(role), frozenset(), frozenset(background)
    )
    assert result <= parent
    assert result <= role
    assert result <= background
    assert "agent" not in result
    assert "task_cancel" not in result
