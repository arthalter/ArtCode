from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from hypothesis import given, settings, strategies as st

from artcode.mcp.adapter import create_adapter
from artcode.mcp.manager import McpManager
from artcode.mcp.models import (
    McpServerReport,
    McpStartupReport,
    ServerSource,
    ServerState,
)
from artcode.mcp.redaction import sanitize_external_text
from artcode.mcp.results import convert_call_result
from artcode.tools import ToolRegistry, create_default_tool_registry


pytestmark = [pytest.mark.ch10_5, pytest.mark.property]
COMPONENT = st.text(
    alphabet=st.sampled_from(list("abcdefghijklmnopqrstuvwxyz0123456789")),
    min_size=1,
    max_size=20,
)


@settings(max_examples=50)
@given(base=COMPONENT, separator=st.sampled_from((" ", ".", "/", ":", "@@")))
def test_normalized_registration_collisions_preserve_builtins(
    base: str,
    separator: str,
) -> None:
    first_server = f"{base}{separator}server"
    second_server = f"{base} server"
    manager = McpManager((), Path.cwd())
    remote = SimpleNamespace(
        name="echo",
        description="echo",
        inputSchema={"type": "object", "properties": {}},
    )
    first = create_adapter(manager, first_server, remote)
    second = create_adapter(manager, second_server, remote)
    if first.name != second.name:
        return
    manager.adapters = (first, second)
    manager._started = True
    manager.report = McpStartupReport(
        2,
        (
            McpServerReport(first_server, ServerSource.USER, ServerState.READY, tool_count=1),
            McpServerReport(second_server, ServerSource.USER, ServerState.READY, tool_count=1),
        ),
        2,
    )
    registry = create_default_tool_registry()
    builtins = tuple(tool.name for tool in registry.all())

    conflicts = manager.register_into(registry)

    assert tuple(tool.name for tool in registry.all())[: len(builtins)] == builtins
    assert len(conflicts) == 1
    assert registry.get(first.name) is first


@settings(max_examples=80)
@given(
    prefix=st.text(alphabet=st.characters(blacklist_categories=("Cs",)), max_size=80),
    secret=st.text(
        alphabet=st.sampled_from(list("abcdefghijklmnopqrstuvwxyz0123456789-_")),
        min_size=4,
        max_size=40,
    ),
    suffix=st.text(alphabet=st.characters(blacklist_categories=("Cs",)), max_size=80),
)
def test_external_errors_are_single_line_and_remove_every_configured_secret(
    prefix: str,
    secret: str,
    suffix: str,
) -> None:
    raw = f"{prefix}\n{secret}\r{suffix}{secret}"
    sanitized = sanitize_external_text(raw, (secret,))
    assert secret not in sanitized
    assert "\n" not in sanitized
    assert "\r" not in sanitized
    assert len(sanitized) <= 500


@settings(max_examples=60)
@given(
    payload=st.binary(max_size=1_000),
    mime=st.sampled_from(("image/png", "audio/wav", "application/octet-stream")),
)
def test_non_text_mcp_content_never_exposes_binary_payload(
    payload: bytes,
    mime: str,
) -> None:
    result = SimpleNamespace(
        isError=False,
        content=(SimpleNamespace(type="image", mimeType=mime, data=payload),),
        structuredContent=None,
    )

    converted = convert_call_result("mcp__server__asset", result)

    assert converted.ok
    assert mime in converted.content
    assert repr(payload) not in converted.content
