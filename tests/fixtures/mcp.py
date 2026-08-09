from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class FakeMcpSession:
    tools: tuple[dict[str, Any], ...] = ()
    close_count: int = 0
    failure: Exception | None = None

    async def list_tools(self) -> tuple[dict[str, Any], ...]:
        if self.failure is not None:
            raise self.failure
        return self.tools

    async def close(self) -> None:
        self.close_count += 1
