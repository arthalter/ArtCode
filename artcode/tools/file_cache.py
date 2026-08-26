from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FileCacheEntry:
    text: str
    mtime_ns: int
    size: int


class FileReadCache:
    """Per-agent cache of absolute-path text reads.

    Keys are normalized absolute paths so two sub-agents working in
    different Worktrees can never alias each other through the same
    relative path. Entries are validated against the file's current
    mtime and size before reuse, so a modified file is re-read instead
    of serving stale content.
    """

    def __init__(self, max_entries: int = 512) -> None:
        if max_entries <= 0:
            raise ValueError("max_entries must be positive")
        self.max_entries = max_entries
        self._entries: dict[Path, FileCacheEntry] = {}

    def get(self, path: Path) -> str | None:
        key = path.expanduser().resolve()
        entry = self._entries.get(key)
        if entry is None:
            return None
        try:
            stat = key.stat()
        except OSError:
            del self._entries[key]
            return None
        if stat.st_mtime_ns != entry.mtime_ns or stat.st_size != entry.size:
            del self._entries[key]
            return None
        return entry.text

    def put(self, path: Path, text: str) -> None:
        key = path.expanduser().resolve()
        try:
            stat = key.stat()
        except OSError:
            return
        if key not in self._entries and len(self._entries) >= self.max_entries:
            # Bound memory by evicting the least recently stored entry.
            oldest = next(iter(self._entries))
            del self._entries[oldest]
        self._entries[key] = FileCacheEntry(text, stat.st_mtime_ns, stat.st_size)

    def clear(self) -> None:
        self._entries.clear()

    @property
    def size(self) -> int:
        return len(self._entries)

    def __contains__(self, path: Path) -> bool:
        return path.expanduser().resolve() in self._entries
