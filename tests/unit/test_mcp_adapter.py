from types import SimpleNamespace

import pytest

from artcode.mcp.adapter import create_adapter, validate_schema
from artcode.tools import ToolOrigin


def test_adapter_has_mcp_origin_and_fallback_description() -> None:
    adapter = create_adapter(
        object(),
        "demo",
        SimpleNamespace(name="echo", description=None, inputSchema={"type": "object", "properties": {}}),
    )
    assert adapter.name == "mcp__demo__echo"
    assert adapter.origin is ToolOrigin.MCP
    assert "demo" in adapter.description


def test_invalid_required_is_rejected() -> None:
    with pytest.raises(ValueError):
        validate_schema({"type": "object", "properties": {}, "required": ["missing"]})
