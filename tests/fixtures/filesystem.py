from __future__ import annotations

from pathlib import Path


class InjectedFilesystemFailure(OSError):
    pass


class FaultyAtomicWriter:
    """Small deterministic fault surface used by atomic-write contract tests."""

    STAGES = ("open", "flush", "fsync", "replace", "cleanup")

    def __init__(self, fail_at: str) -> None:
        if fail_at not in self.STAGES:
            raise ValueError(f"unknown failure stage: {fail_at}")
        self.fail_at = fail_at
        self.visited: list[str] = []

    def visit(self, stage: str, path: Path) -> None:
        if stage not in self.STAGES:
            raise ValueError(stage)
        self.visited.append(f"{stage}:{path.name}")
        if stage == self.fail_at:
            raise InjectedFilesystemFailure(stage)
