from __future__ import annotations

import json
import os
from pathlib import Path
import re
import secrets
import tempfile


SESSION_ID = re.compile(r"session-[0-9]+-[0-9a-f]{8}\Z")


def sessions_root(workspace: Path) -> Path:
    return workspace / ".artcode" / "ch14" / "sessions"


def new_session_id(clock_value: float) -> str:
    return f"session-{int(clock_value * 1_000_000)}-{secrets.token_hex(4)}"


def validate_session_id(value: str) -> str:
    if not isinstance(value, str) or SESSION_ID.fullmatch(value) is None:
        raise ValueError("Session ID 格式无效。")
    return value


def write_metadata(path: Path, *, session_id: str, created_at: float, workspace: Path) -> None:
    payload = {
        "version": 1,
        "session_id": session_id,
        "created_at": created_at,
        "workspace": str(workspace),
    }
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, prefix=".metadata-", delete=False
        ) as handle:
            temporary = handle.name
            os.chmod(temporary, 0o600)
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


def read_metadata(path: Path, workspace: Path) -> tuple[str, float] | None:
    try:
        if path.is_symlink() or not path.is_file():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if (
        not isinstance(raw, dict)
        or set(raw) != {"version", "session_id", "created_at", "workspace"}
        or raw["version"] != 1
        or not isinstance(raw["session_id"], str)
        or isinstance(raw["created_at"], bool)
        or not isinstance(raw["created_at"], (int, float))
        or raw["workspace"] != str(workspace)
    ):
        return None
    try:
        validate_session_id(raw["session_id"])
    except ValueError:
        return None
    return raw["session_id"], float(raw["created_at"])
