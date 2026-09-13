from __future__ import annotations

from hypothesis import given, strategies as st

from artcode._tool.mcp_config import load_configs
from artcode.core.tool import McpServerSource


NAMES = st.text(
    alphabet=st.sampled_from(list("abcXYZ09 _-/中文")), min_size=1, max_size=20
).filter(lambda value: bool(value.strip()))


@given(NAMES)
def test_project_definition_wholly_replaces_same_named_user_definition(name: str) -> None:
    user = {name: {"transport": "stdio", "enabled": False, "command": "user", "args": ["u"]}}
    project = {name: {"transport": "stdio", "enabled": False, "command": "project", "args": ["p"]}}

    configs, issues = load_configs(user, project, environ={})

    assert not issues
    assert len(configs) == 1
    assert configs[0].source is McpServerSource.PROJECT
    assert configs[0].command == "project"
    assert configs[0].args == ("p",)


@given(NAMES, NAMES)
def test_registered_names_are_bounded_and_deterministic(server: str, tool: str) -> None:
    from artcode._tool.mcp_config import registered_name

    first = registered_name(server, tool)
    assert first == registered_name(server, tool)
    assert len(first) <= 64
    assert first.startswith("mcp__")
