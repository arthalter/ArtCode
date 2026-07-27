from __future__ import annotations

import json
from typing import Any

from artcode.tools.results import MAX_RESULT_BYTES, ToolResult, error_result, success_result


def convert_call_result(tool_name: str, result: Any, max_bytes: int = MAX_RESULT_BYTES) -> ToolResult:
    blocks: list[str] = []
    for block in getattr(result, "content", ()) or ():
        kind = getattr(block, "type", type(block).__name__)
        if kind == "text":
            blocks.append(str(getattr(block, "text", "")))
        elif kind == "resource":
            resource = getattr(block, "resource", None)
            blocks.append(json.dumps({"type": "resource", "uri": str(getattr(resource, "uri", ""))}, ensure_ascii=False))
        else:
            metadata = {"type": str(kind)}
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
        return error_result(tool_name, "mcp_tool_error", "MCP Server 返回工具错误。", content, max_bytes)
    return success_result(tool_name, "MCP 工具执行成功。", content, max_bytes)
