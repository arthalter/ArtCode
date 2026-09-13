from __future__ import annotations

import json
from typing import Any

from artcode.core.tool import ToolCall, ToolResult

from .results import failure, success


def convert_result(call: ToolCall, result: Any) -> ToolResult:
    blocks: list[str] = []
    for block in getattr(result, "content", ()) or ():
        kind = str(getattr(block, "type", type(block).__name__))
        if kind == "text":
            blocks.append(str(getattr(block, "text", "")))
        elif kind == "resource":
            resource = getattr(block, "resource", None)
            payload: dict[str, str] = {
                "type": "resource",
                "uri": str(getattr(resource, "uri", "")),
            }
            text = getattr(resource, "text", None)
            if isinstance(text, str):
                payload["text"] = text
            else:
                mime = getattr(resource, "mimeType", None)
                if mime:
                    payload["mimeType"] = str(mime)
            blocks.append(json.dumps(payload, ensure_ascii=False))
        else:
            metadata = {"type": kind}
            for key in ("mimeType", "name"):
                value = getattr(block, key, None)
                if value:
                    metadata[key] = str(value)
            blocks.append(json.dumps(metadata, ensure_ascii=False))
    structured = getattr(result, "structuredContent", None)
    if structured is not None:
        blocks.append(json.dumps(structured, ensure_ascii=False, sort_keys=True, default=str))
    content = "\n".join(blocks)
    if getattr(result, "isError", False):
        return failure(call, "mcp_tool_error", content or "MCP Server 返回工具错误。")
    return success(call, content)


def sanitize(text: object, secrets: tuple[str, ...], *, limit: int = 2_000) -> str:
    safe = str(text)
    for secret in secrets:
        if secret:
            safe = safe.replace(secret, "[REDACTED]")
    if len(safe) > limit:
        return safe[:limit] + "…"
    return safe
