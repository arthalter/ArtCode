from __future__ import annotations

import tempfile

from .redaction import sanitize_external_text


class StderrCapture:
    """Seekable file-backed stderr sink that cannot apply pipe backpressure."""

    def __init__(self, secrets: tuple[str, ...] = ()) -> None:
        self._file = tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace")
        self._secrets = secrets

    @property
    def stream(self):
        return self._file

    def recent(self, max_lines: int = 100, max_bytes: int = 65_536, line_limit: int = 2_048) -> str:
        self._file.flush()
        self._file.seek(0)
        lines = self._file.readlines()[-max_lines:]
        cleaned = [sanitize_external_text(line[:line_limit], self._secrets, line_limit) for line in lines]
        text = "\n".join(cleaned)
        encoded = text.encode("utf-8")
        return text if len(encoded) <= max_bytes else encoded[-max_bytes:].decode("utf-8", errors="ignore")

    def close(self) -> None:
        self._file.close()
