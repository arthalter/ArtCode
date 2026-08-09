from __future__ import annotations

import asyncio
from types import SimpleNamespace
from pathlib import Path

import pytest

import artcode.mcp.manager as manager_module
from artcode.mcp.adapter import create_adapter
from artcode.mcp.manager import McpManager
from artcode.mcp.models import (
    FailureStage,
    McpServerConfig,
    McpServerReport,
    McpStartupReport,
    ServerSource,
    ServerState,
    TransportKind,
)
from artcode.mcp.session import McpSession
from artcode.tools import (
    DescriptorBackedTool,
    PreparedToolCall,
    ToolDescriptor,
    ToolEffect,
    ToolPreview,
    ToolRegistry,
)


pytestmark = pytest.mark.ch10_5


def _config(
    name: str,
    *,
    source: ServerSource = ServerSource.USER,
    enabled: bool = True,
    referenced: tuple[str, ...] = (),
    headers: dict[str, str] | None = None,
) -> McpServerConfig:
    if headers is not None:
        return McpServerConfig(
            name,
            TransportKind.STREAMABLE_HTTP,
            source,
            enabled,
            url="https://example.invalid/mcp",
            headers=headers,
        )
    return McpServerConfig(
        name,
        TransportKind.STDIO,
        source,
        enabled,
        command="python",
        referenced_variables=referenced,
    )


def _tool(name: str = "echo", schema=None):
    return SimpleNamespace(
        name=name,
        description=f"tool {name}",
        inputSchema=schema or {"type": "object", "properties": {}},
    )


@pytest.mark.parametrize(
    "scenario",
    ["disabled", "project-no-approver", "project-rejected", "approval-error", "missing-env"],
)
async def test_startup_preconnection_failures_are_local_reports(
    tmp_path: Path,
    scenario: str,
) -> None:
    if scenario == "disabled":
        config = _config("one", enabled=False)
        approver = None
        expected = ServerState.DISABLED
    elif scenario == "missing-env":
        config = _config("one", referenced=("ARTCODE_CH10_5_MISSING",))
        approver = None
        expected = ServerState.INVALID
    else:
        config = _config("one", source=ServerSource.PROJECT)
        expected = ServerState.REJECTED if scenario != "approval-error" else ServerState.UNAVAILABLE
        if scenario == "project-no-approver":
            approver = None
        elif scenario == "project-rejected":
            async def approver(_config):
                return False
        else:
            async def approver(_config):
                raise RuntimeError("approval failed")
    manager = McpManager((config,), tmp_path, approver=approver)

    report = await manager.start()

    assert report.server_reports[0].state is expected
    assert report.registered_tool_count == 0
    if scenario == "approval-error":
        assert report.server_reports[0].failure_stage is FailureStage.APPROVAL
    await manager.close()


@pytest.mark.parametrize("healthy_count", [1, 2, 3, 5])
async def test_connection_failure_does_not_hide_healthy_servers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    healthy_count: int,
) -> None:
    class FakeSession:
        def __init__(self, config, workspace):
            self.config = config
            self.truncated = False

        async def connect(self):
            if self.config.name == "broken":
                raise ConnectionError("controlled")
            return (_tool("echo"),)

        async def close(self):
            return None

        async def call_tool(self, name, arguments):
            return arguments

    monkeypatch.setattr(manager_module, "McpSession", FakeSession)
    configs = (_config("broken"), *(_config(f"healthy-{i}") for i in range(healthy_count)))
    manager = McpManager(tuple(configs), tmp_path)

    report = await manager.start()

    assert report.connected_count == healthy_count
    assert report.failed_count == 1
    assert len(manager.adapters) == healthy_count
    assert set(manager.sessions) == {f"healthy-{i}" for i in range(healthy_count)}
    await manager.close()


@pytest.mark.parametrize(
    ("tools", "registered", "issues"),
    [
        ((_tool(""),), 0, 1),
        ((_tool("bad", {"type": "array"}),), 0, 1),
        ((_tool("a/b"), _tool("a b")), 1, 1),
        ((_tool("ok"), _tool("", {"type": "array"})), 1, 1),
        ((_tool("one"), _tool("two"), _tool("three")), 3, 0),
    ],
)
async def test_invalid_or_duplicate_remote_tools_are_observable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tools: tuple,
    registered: int,
    issues: int,
) -> None:
    class FakeSession:
        truncated = False

        def __init__(self, config, workspace):
            self.config = config

        async def connect(self):
            return tools

        async def close(self):
            return None

    monkeypatch.setattr(manager_module, "McpSession", FakeSession)
    manager = McpManager((_config("server"),), tmp_path)

    report = await manager.start()
    server = report.server_reports[0]

    assert server.tool_count == registered
    assert len(server.registration_issues) == issues
    assert report.registration_issue_count == issues
    assert (server.failure_stage is FailureStage.REGISTRATION) is bool(issues)
    await manager.close()


@pytest.mark.parametrize(
    ("first", "second"),
    [("a b", "a__b"), ("a/b", "a b"), ("é", "unnamed"), ("a.b", "a/b")],
)
async def test_cross_server_normalized_name_collision_keeps_first_server(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    first: str,
    second: str,
) -> None:
    class FakeSession:
        truncated = False

        def __init__(self, config, workspace):
            self.config = config

        async def connect(self):
            return (_tool("echo"),)

        async def close(self):
            return None

    monkeypatch.setattr(manager_module, "McpSession", FakeSession)
    manager = McpManager((_config(first), _config(second)), tmp_path)

    report = await manager.start()

    assert len(manager.adapters) == 1
    assert manager.adapters[0].server_name == first
    assert report.registration_issue_count == 1
    assert report.server_reports[1].failure_stage is FailureStage.REGISTRATION
    await manager.close()


class ExistingTool(DescriptorBackedTool):
    def __init__(self, name: str) -> None:
        self.descriptor = ToolDescriptor(
            name,
            "existing",
            {"type": "object", "properties": {}},
            ToolEffect.READ,
        )

    def prepare(self, arguments, context):
        raise NotImplementedError

    async def execute(self, prepared, context):
        raise NotImplementedError


@pytest.mark.parametrize("preexisting", [0, 1, 2])
def test_register_into_preserves_existing_tools_and_is_idempotent(preexisting: int) -> None:
    manager = McpManager((), Path.cwd())
    adapters = tuple(create_adapter(manager, "server", _tool(name)) for name in ("one", "two"))
    manager.adapters = adapters
    manager._started = True
    manager.report = McpStartupReport(
        1,
        (McpServerReport("server", ServerSource.USER, ServerState.READY, tool_count=2),),
        2,
    )
    registry = ToolRegistry()
    for adapter in adapters[:preexisting]:
        registry.register(ExistingTool(adapter.name))

    conflicts = manager.register_into(registry)

    assert len(conflicts) == preexisting
    assert len(manager.adapters) == 2 - preexisting
    assert manager.report.registered_tool_count == 2 - preexisting
    assert manager.register_into(registry) == ()


@pytest.mark.parametrize("active_count", [0, 1, 5])
async def test_manager_close_awaits_every_cancelled_active_call(
    tmp_path: Path,
    active_count: int,
) -> None:
    cancelled: list[int] = []
    started: list[int] = []
    all_started = asyncio.Event()

    class BlockingSession:
        async def call_tool(self, name, arguments):
            started.append(arguments["index"])
            if len(started) == active_count:
                all_started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.append(arguments["index"])
                raise

        async def close(self):
            return None

    manager = McpManager((), tmp_path)
    manager.sessions["server"] = BlockingSession()
    calls = [
        asyncio.create_task(manager.call_tool("server", "wait", {"index": index}))
        for index in range(active_count)
    ]
    if calls:
        await asyncio.wait_for(all_started.wait(), timeout=1)

    await manager.close()

    results = await asyncio.gather(*calls, return_exceptions=True)
    assert all(isinstance(item, asyncio.CancelledError) for item in results)
    assert sorted(cancelled) == list(range(active_count))
    assert not manager._active_calls


@pytest.mark.parametrize("failure", [ConnectionError, EOFError, RuntimeError])
async def test_session_call_errors_redact_configured_header_secret(
    tmp_path: Path,
    failure: type[Exception],
) -> None:
    secret = "Bearer unit-secret"

    class FaultClient:
        async def call_tool(self, name, arguments, read_timeout_seconds=None):
            raise failure(f"external said {secret}")

    session = McpSession(_config("http", headers={"Authorization": secret}), tmp_path)
    session._client = FaultClient()
    session.state = ServerState.READY

    with pytest.raises(RuntimeError) as raised:
        await session.call_tool("echo", {})

    assert secret not in str(raised.value)
    assert "***" in str(raised.value)
    assert session.state is ServerState.UNAVAILABLE


@pytest.mark.parametrize("behavior", ["schema-copy", "cancel", "error-result"])
async def test_adapter_boundary_is_detached_and_structured(behavior: str) -> None:
    schema = {"type": "object", "properties": {"text": {"type": "string"}}}

    class Manager:
        async def call_tool(self, server, tool, arguments):
            if behavior == "cancel":
                raise asyncio.CancelledError
            raise RuntimeError("remote failed")

    adapter = create_adapter(Manager(), "server", _tool("echo", schema))
    if behavior == "schema-copy":
        schema["properties"]["text"]["type"] = "number"
        assert adapter.parameters_schema["properties"]["text"]["type"] == "string"
        return
    prepared = PreparedToolCall(
        adapter,
        {},
        ToolPreview(adapter.name, "{}", "server/echo", True),
    )
    if behavior == "cancel":
        with pytest.raises(asyncio.CancelledError):
            await adapter.execute(prepared, None)
    else:
        result = await adapter.execute(prepared, None)
        assert not result.ok
        assert result.error_code == "mcp_call_failed"
