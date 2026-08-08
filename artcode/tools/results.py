from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass(frozen=True)
class ToolResult:
    tool_name: str
    ok: bool
    status: str
    message: str
    content: str = ""
    error_code: str | None = None
    bytes_returned: int = 0

    def to_model_content(self) -> str:
        return json.dumps(
            {
                "tool_name": self.tool_name,
                "ok": self.ok,
                "status": self.status,
                "message": self.message,
                "content": self.content,
                "error_code": self.error_code,
                "bytes_returned": self.bytes_returned,
            },
            ensure_ascii=False,
        )


def success_result(
    tool_name: str,
    message: str,
    content: str = "",
) -> ToolResult:
    return ToolResult(
        tool_name=tool_name,
        ok=True,
        status="success",
        message=message,
        content=content,
        bytes_returned=len(content.encode("utf-8")),
    )


def error_result(
    tool_name: str,
    error_code: str,
    message: str,
    content: str = "",
) -> ToolResult:
    return ToolResult(
        tool_name=tool_name,
        ok=False,
        status="error",
        message=message,
        content=content,
        error_code=error_code,
        bytes_returned=len(content.encode("utf-8")),
    )


def denied_result(tool_name: str, message: str = "用户拒绝执行该工具。") -> ToolResult:
    return ToolResult(
        tool_name=tool_name,
        ok=False,
        status="denied",
        message=message,
        error_code="user_denied",
    )
