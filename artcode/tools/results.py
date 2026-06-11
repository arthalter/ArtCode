from __future__ import annotations

import json
from dataclasses import dataclass


MAX_RESULT_BYTES = 20_000


@dataclass(frozen=True)
class ToolResult:
    tool_name: str
    ok: bool
    status: str
    message: str
    content: str = ""
    error_code: str | None = None
    truncated: bool = False
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
                "truncated": self.truncated,
                "bytes_returned": self.bytes_returned,
            },
            ensure_ascii=False,
        )


def success_result(
    tool_name: str,
    message: str,
    content: str = "",
    max_bytes: int = MAX_RESULT_BYTES,
) -> ToolResult:
    truncated_content, truncated, bytes_returned = truncate_text(content, max_bytes)
    return ToolResult(
        tool_name=tool_name,
        ok=True,
        status="success",
        message=message,
        content=truncated_content,
        truncated=truncated,
        bytes_returned=bytes_returned,
    )


def error_result(
    tool_name: str,
    error_code: str,
    message: str,
    content: str = "",
    max_bytes: int = MAX_RESULT_BYTES,
) -> ToolResult:
    truncated_content, truncated, bytes_returned = truncate_text(content, max_bytes)
    return ToolResult(
        tool_name=tool_name,
        ok=False,
        status="error",
        message=message,
        content=truncated_content,
        error_code=error_code,
        truncated=truncated,
        bytes_returned=bytes_returned,
    )


def denied_result(tool_name: str, message: str = "用户拒绝执行该工具。") -> ToolResult:
    return ToolResult(
        tool_name=tool_name,
        ok=False,
        status="denied",
        message=message,
        error_code="user_denied",
    )


def truncate_text(text: str, max_bytes: int) -> tuple[str, bool, int]:
    data = text.encode("utf-8")
    if len(data) <= max_bytes:
        return text, False, len(data)

    truncated_data = data[:max_bytes]
    while truncated_data:
        try:
            truncated_text = truncated_data.decode("utf-8")
            return truncated_text, True, len(truncated_data)
        except UnicodeDecodeError:
            truncated_data = truncated_data[:-1]

    return "", True, 0
