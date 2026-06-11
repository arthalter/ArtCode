from __future__ import annotations

import pytest

from artcode.tools.registry import ToolRegistry, create_default_tool_registry


def test_default_registry_contains_six_core_tools() -> None:
    registry = create_default_tool_registry()

    for name in ["read_file", "write_file", "edit_file", "run_command", "find_files", "search_text"]:
        assert registry.get(name) is not None


def test_registry_requires_known_tool() -> None:
    registry = create_default_tool_registry()

    assert registry.require("read_file").name == "read_file"


def test_registry_rejects_unknown_tool() -> None:
    registry = create_default_tool_registry()

    with pytest.raises(KeyError, match="Unknown tool"):
        registry.require("missing")


def test_registry_rejects_duplicate_tool() -> None:
    registry = ToolRegistry()
    tool = create_default_tool_registry().require("read_file")

    registry.register(tool)
    with pytest.raises(ValueError, match="already registered"):
        registry.register(tool)


def test_openai_tools_export_shape() -> None:
    registry = create_default_tool_registry()

    exported = registry.openai_tools()

    assert len(exported) == 6
    assert all(item["type"] == "function" for item in exported)
    names = {item["function"]["name"] for item in exported}
    assert "read_file" in names
    assert all("description" in item["function"] for item in exported)
    assert all("parameters" in item["function"] for item in exported)
