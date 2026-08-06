from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from artcode.mcp.manager import McpManager


class BlockingSession:
    def __init__(self, *, close_error: bool = False) -> None:
        self.started = asyncio.Event()
        self.cancelled = 0
        self.closed = 0
        self.close_error = close_error

    async def call_tool(self, name, arguments):
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled += 1
            raise

    async def close(self):
        self.closed += 1
        if self.close_error:
            raise RuntimeError("controlled close failure")


class ImmediateSession:
    def __init__(self) -> None:
        self.closed = 0

    async def call_tool(self, name, arguments):
        await asyncio.sleep(0)
        return arguments["value"]

    async def close(self):
        self.closed += 1


async def test_close_cancels_active_calls_and_rejects_new_calls(tmp_path: Path) -> None:
    manager = McpManager((), tmp_path)
    session = BlockingSession()
    manager.sessions["slow"] = session
    calls = [
        asyncio.create_task(manager.call_tool("slow", "wait", {"index": index}))
        for index in range(3)
    ]
    await session.started.wait()

    await asyncio.wait_for(manager.close(), timeout=3.5)

    results = await asyncio.gather(*calls, return_exceptions=True)
    assert all(isinstance(result, asyncio.CancelledError) for result in results)
    assert session.cancelled == 3
    assert session.closed == 1
    assert not manager._active_calls
    with pytest.raises(RuntimeError, match="不再接受新调用"):
        await manager.call_tool("slow", "wait", {})


async def test_close_failure_isolated_between_sessions(tmp_path: Path) -> None:
    manager = McpManager((), tmp_path)
    broken = BlockingSession(close_error=True)
    healthy = ImmediateSession()
    manager.sessions.update(broken=broken, healthy=healthy)

    await manager.close()

    assert broken.closed == 1
    assert healthy.closed == 1


async def test_response_cancel_race_has_one_terminal_outcome(tmp_path: Path) -> None:
    for _ in range(50):
        manager = McpManager((), tmp_path)
        session = ImmediateSession()
        manager.sessions["fast"] = session
        call = asyncio.create_task(manager.call_tool("fast", "echo", {"value": "ok"}))
        await asyncio.sleep(0)
        call.cancel()
        outcome = await asyncio.gather(call, return_exceptions=True)

        assert outcome == ["ok"] or isinstance(outcome[0], asyncio.CancelledError)
        await asyncio.sleep(0)
        assert not manager._active_calls
        await manager.close()
