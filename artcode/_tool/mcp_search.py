from __future__ import annotations

import json
from typing import Any

from artcode.core.tool import ToolCall, ToolDescriptor, ToolEffect, ToolOrigin, ToolResult, ToolRun

from .builtin import Prepared, _schema
from .mcp import McpAdapter
from .results import failure, success


DESCRIPTOR = ToolDescriptor(
    "mcp_search_tools",
    "搜索已发现的 MCP 工具并激活命中项。工具从下一次模型请求起可用；本次搜索不执行远程工具。",
    _schema(
        {
            "query": {"type": "string", "minLength": 1},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 5},
        },
        ["query"],
    ),
    ToolEffect.CONTROL,
    ToolOrigin.SYSTEM,
    subagent_allowed=False,
    rule_configurable=False,
)


def prepare_search(
    adapter: McpAdapter,
    call: ToolCall,
    arguments: dict[str, Any],
    run: ToolRun,
) -> Prepared | ToolResult:
    query = arguments.get("query")
    limit = arguments.get("limit", 5)
    if (
        set(arguments) - {"query", "limit"}
        or not isinstance(query, str)
        or not query.strip()
        or type(limit) is not int
        or not 1 <= limit <= 50
    ):
        return failure(call, "invalid_arguments", "mcp_search_tools 需要非空 query，limit 必须为 1 到 50 的整数。")

    async def execute() -> ToolResult:
        hits = adapter.search(query, limit=limit, allowed_tools=run.allowed_tools)
        found: list[dict[str, object]] = []
        for hit in hits:
            active = adapter.activate(hit.name)
            found.append({
                "name": hit.name,
                "description": hit.description,
                "server": hit.server,
                "active": active,
                "status": "available_next_request" if active else "server_unavailable",
            })
        return success(call, json.dumps({
            "tools": found,
            "message": "active 为 true 的工具从下一次模型请求起可用；当前批次工具目录保持不变。",
        }, ensure_ascii=False))

    return Prepared(call, DESCRIPTOR, query, execute)
