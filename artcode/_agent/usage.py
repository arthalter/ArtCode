from __future__ import annotations

from artcode.core.model import Usage


class UsageAccumulator:
    def __init__(self) -> None:
        self._values: list[int | None] = [None, None, None, None, None]

    def add(self, usage: Usage) -> Usage:
        incoming = (
            usage.input_tokens,
            usage.output_tokens,
            usage.total_tokens,
            usage.cached_tokens,
            usage.cache_miss_tokens,
        )
        for index, value in enumerate(incoming):
            if value is not None:
                self._values[index] = (self._values[index] or 0) + value
        return self.snapshot()

    def snapshot(self) -> Usage:
        return Usage(*self._values)
