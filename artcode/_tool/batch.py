from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from artcode.core.tool import ToolCall, ToolDescriptor, ToolEffect, ToolResult


async def execute_ordered_batches(
    calls: tuple[ToolCall, ...],
    descriptor_for: Callable[[str], ToolDescriptor | None],
    execute_one: Callable[[ToolCall], Awaitable[ToolResult]],
) -> tuple[ToolResult, ...]:
    results: list[ToolResult] = []
    observe: list[ToolCall] = []

    async def flush_observe() -> None:
        if observe:
            results.extend(await asyncio.gather(*(execute_one(call) for call in observe)))
            observe.clear()

    for call in calls:
        descriptor = descriptor_for(call.name)
        if descriptor is not None and descriptor.effect is ToolEffect.OBSERVE:
            observe.append(call)
            continue
        await flush_observe()
        results.append(await execute_one(call))
    await flush_observe()
    return tuple(results)
