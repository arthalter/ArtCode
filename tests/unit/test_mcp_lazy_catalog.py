from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from artcode.mcp.adapter import create_adapter
from artcode.mcp.manager import McpManager
from artcode.mcp.models import (
    McpLoadingStrategy,
    McpServerReport,
    McpStartupReport,
    ServerSource,
    ServerState,
)
from artcode.tools import DescriptorBackedTool, ToolDescriptor, ToolEffect, ToolRegistry


def _tool(name: str, description: str, field: str = "query"):
    return SimpleNamespace(
        name=name,
        description=description,
        inputSchema={
            "type": "object",
            "properties": {field: {"type": "string"}},
        },
    )


def _manager(tmp_path: Path, tools: tuple) -> McpManager:
    manager = McpManager((), tmp_path, loading=McpLoadingStrategy.LAZY)
    manager.adapters = tuple(create_adapter(manager, "catalog", tool) for tool in tools)
    manager.catalog = __import__(
        "artcode.mcp.catalog", fromlist=["McpCatalog"]
    ).McpCatalog(manager.adapters)
    manager._started = True
    manager.report = McpStartupReport(
        configured_count=1,
        server_reports=(
            McpServerReport("catalog", ServerSource.USER, ServerState.READY, len(tools)),
        ),
        discovered_tool_count=len(tools),
        loading_strategy=McpLoadingStrategy.LAZY,
    )
    return manager


def test_lazy_registry_only_exposes_search_then_matching_tool(tmp_path: Path) -> None:
    manager = _manager(
        tmp_path,
        (
            _tool("customer_risk", "lookup customer fraud risk", "customer_id"),
            _tool("release_notes", "summarize product release notes", "version"),
        ),
    )
    registry = ToolRegistry()

    assert manager.register_into(registry) == ()
    assert [item.name for item in registry.descriptors()] == ["mcp_search_tools"]
    hits, activations = manager.search_and_activate("customer fraud", limit=2)

    assert [hit.remote_name for hit in hits] == ["customer_risk"]
    assert activations[0].status == "activated"
    assert registry.get(hits[0].name) is manager.catalog.get(hits[0].name)
    assert manager.activate(hits[0].name).status == "already_active"
    assert manager.report.registered_tool_count == 1


def test_lazy_search_uses_name_description_and_schema_deterministically(
    tmp_path: Path,
) -> None:
    manager = _manager(
        tmp_path,
        (
            _tool("zeta", "incident owner lookup", "incident_id"),
            _tool("alpha", "incident owner lookup", "ticket_id"),
            _tool("shipping", "calculate quote", "postal_code"),
        ),
    )
    manager.register_into(ToolRegistry())

    assert [hit.remote_name for hit in manager.search("incident owner")] == [
        "zeta",
        "alpha",
    ]
    assert [hit.remote_name for hit in manager.search("postal_code")] == ["shipping"]
    assert manager.search("no-such-capability") == ()
    assert manager.activate("mcp__catalog__missing").status == "not_found"


class ExistingTool(DescriptorBackedTool):
    def __init__(self, name: str) -> None:
        self.descriptor = ToolDescriptor(
            name,
            "existing",
            {"type": "object", "properties": {}},
            ToolEffect.READ,
        )


def test_lazy_activation_conflict_and_close_are_observable(tmp_path: Path) -> None:
    manager = _manager(tmp_path, (_tool("echo", "echo a value"),))
    registry = ToolRegistry()
    manager.register_into(registry)
    name = manager.adapters[0].name
    registry.register(ExistingTool(name))

    assert manager.activate(name).status == "conflict"
    manager._accepting = False
    assert manager.activate(name).status == "closed"
