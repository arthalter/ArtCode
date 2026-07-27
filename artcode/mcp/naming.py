from __future__ import annotations

import hashlib
import re


MAX_TOOL_NAME_LENGTH = 64


def normalize_component(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_-]+", "_", value.strip())
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    return normalized or "unnamed"


def registered_tool_name(server_name: str, tool_name: str) -> str:
    raw = f"mcp__{normalize_component(server_name)}__{normalize_component(tool_name)}"
    if len(raw) <= MAX_TOOL_NAME_LENGTH:
        return raw
    suffix = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:10]
    return f"{raw[: MAX_TOOL_NAME_LENGTH - 12]}__{suffix}"
