from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from artcode.tools.base import (
    PreparedToolCall,
    ToolApprovalPolicy,
    ToolExecutionContext,
    ToolOrigin,
    ToolPreview,
)
from artcode.tools.results import ToolResult, error_result

from .naming import registered_tool_name
from .redaction import safe_json_preview, sanitize_external_text
from .results import convert_call_result


def validate_schema(schema: Any) -> dict[str, Any]:
    if not isinstance(schema, dict) or schema.get("type") != "object":
        raise ValueError("inputSchema 顶层 type 必须是 object。")
    properties = schema.get("properties", {})
    required = schema.get("required", [])
    if not isinstance(properties, dict) or not isinstance(required, list):
        raise ValueError("inputSchema 的 properties 必须是对象，required 必须是列表。")
    if any(not isinstance(item, str) or item not in properties for item in required):
        raise ValueError("inputSchema.required 必须只引用 properties 中的字符串字段。")
    return schema


@dataclass(frozen=True)
class McpToolAdapter:
    manager: Any
    name: str
    remote_name: str
    server_name: str
    description: str
    parameters_schema: dict[str, Any]
    requires_confirmation: bool = True
    origin: ToolOrigin = ToolOrigin.MCP
    approval_policy: ToolApprovalPolicy = ToolApprovalPolicy.ALWAYS_ASK_ONCE

    def prepare(self, arguments: dict[str, Any], context: ToolExecutionContext):
        return PreparedToolCall(
            self,
            arguments,
            ToolPreview(self.name, safe_json_preview(arguments), f"{self.server_name}/{self.remote_name}", True),
        )

    async def execute(self, prepared: PreparedToolCall, context: ToolExecutionContext) -> ToolResult:
        try:
            result = await self.manager.call_tool(self.server_name, self.remote_name, prepared.arguments)
            return convert_call_result(self.name, result)
        except Exception as exc:
            return error_result(self.name, "mcp_call_failed", sanitize_external_text(str(exc)))


def create_adapter(manager: Any, server_name: str, remote_tool: Any) -> McpToolAdapter:
    remote_name = getattr(remote_tool, "name", "")
    if not isinstance(remote_name, str) or not remote_name.strip():
        raise ValueError("远端工具缺少合法名称。")
    schema = validate_schema(getattr(remote_tool, "inputSchema", None))
    description = getattr(remote_tool, "description", None)
    if not isinstance(description, str) or not description.strip():
        description = f"来自 MCP Server {server_name} 的工具 {remote_name}。"
    return McpToolAdapter(
        manager, registered_tool_name(server_name, remote_name), remote_name,
        server_name, description, schema,
    )
