from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from artcode.tools import (
    DescriptorBackedTool,
    PreparedToolCall,
    ToolDescriptor,
    ToolEffect,
    ToolPreview,
    ToolRunContext,
    error_result,
    success_result,
)


_TERM = re.compile(r"[a-z0-9_]+")


@dataclass(frozen=True)
class McpSearchHit:
    name: str
    server_name: str
    remote_name: str
    description: str
    score: int
    activated: bool


@dataclass(frozen=True)
class McpActivationResult:
    name: str
    status: str
    message: str


class McpCatalog:
    def __init__(self, adapters: tuple[Any, ...]) -> None:
        self._adapters = {adapter.name: adapter for adapter in adapters}

    @property
    def adapters(self) -> tuple[Any, ...]:
        return tuple(self._adapters[name] for name in sorted(self._adapters))

    def get(self, name: str) -> Any | None:
        return self._adapters.get(name)

    def search(
        self,
        query: str,
        *,
        limit: int = 5,
        activated_names: frozenset[str] = frozenset(),
    ) -> tuple[McpSearchHit, ...]:
        normalized = " ".join(query.lower().split())
        terms = tuple(dict.fromkeys(_TERM.findall(normalized)))
        if not terms:
            return ()
        hits: list[McpSearchHit] = []
        for adapter in self.adapters:
            registered = adapter.name.lower()
            remote = adapter.remote_name.lower()
            description = adapter.description.lower()
            schema = json.dumps(
                adapter.parameters_schema,
                ensure_ascii=False,
                sort_keys=True,
            ).lower()
            score = 0
            if normalized in {registered, remote}:
                score += 100
            elif normalized in registered or normalized in remote:
                score += 30
            for term in terms:
                if term in registered or term in remote:
                    score += 12
                if term in description:
                    score += 4
                if term in schema:
                    score += 1
            if score <= 0:
                continue
            hits.append(
                McpSearchHit(
                    name=adapter.name,
                    server_name=adapter.server_name,
                    remote_name=adapter.remote_name,
                    description=adapter.description,
                    score=score,
                    activated=adapter.name in activated_names,
                )
            )
        hits.sort(key=lambda item: (-item.score, item.name))
        return tuple(hits[: max(1, min(limit, 20))])


class McpToolSearchTool(DescriptorBackedTool):
    descriptor = ToolDescriptor(
        name="mcp_search_tools",
        description=(
            "按名称、描述和参数字段检索当前会话可用的 MCP 工具。"
            "匹配工具会立即激活，并从下一轮模型请求开始可调用。"
        ),
        parameters_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "工具能力检索词。"},
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 20,
                    "description": "最多返回并激活的工具数，默认 5。",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        effect=ToolEffect.READ,
        rule_configurable=False,
    )

    def __init__(self, manager: Any) -> None:
        self.manager = manager

    def prepare(
        self,
        arguments: dict[str, Any],
        context: ToolRunContext,
    ) -> PreparedToolCall | Any:
        query = arguments.get("query")
        limit = arguments.get("limit", 5)
        if not isinstance(query, str) or not query.strip():
            return error_result(self.name, "invalid_arguments", "query 必须是非空字符串。")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 20:
            return error_result(self.name, "invalid_arguments", "limit 必须是 1～20 的整数。")
        return PreparedToolCall(
            self,
            {"query": query.strip(), "limit": limit},
            ToolPreview(self.name, f"检索 MCP 工具：{query.strip()}", "mcp-catalog"),
        )

    async def execute(
        self,
        prepared: PreparedToolCall,
        context: ToolRunContext,
    ):
        hits, activations = self.manager.search_and_activate(
            prepared.arguments["query"],
            limit=prepared.arguments["limit"],
        )
        payload = {
            "query": prepared.arguments["query"],
            "matches": [
                {
                    "name": hit.name,
                    "server": hit.server_name,
                    "remote_name": hit.remote_name,
                    "description": hit.description,
                    "score": hit.score,
                    "activated": activation.status in {"activated", "already_active"},
                    "activation_status": activation.status,
                }
                for hit, activation in zip(hits, activations)
            ],
        }
        if not hits:
            return success_result(self.name, "没有匹配的 MCP 工具。", json.dumps(payload, ensure_ascii=False))
        return success_result(
            self.name,
            f"找到并处理 {len(hits)} 个 MCP 工具。",
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
        )


__all__ = [
    "McpActivationResult",
    "McpCatalog",
    "McpSearchHit",
    "McpToolSearchTool",
]
