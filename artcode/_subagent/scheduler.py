from __future__ import annotations

import asyncio


class Scheduler:
    def __init__(self, concurrency: int) -> None:
        if concurrency < 1:
            raise ValueError("Subagent 并发数必须为正数。")
        self.semaphore = asyncio.Semaphore(concurrency)
