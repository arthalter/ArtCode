from __future__ import annotations

from artcode.core.tool import ToolCall, ToolResult


def success(call: ToolCall, content: str) -> ToolResult:
    return ToolResult(call.id, call.name, True, content)


def failure(call: ToolCall, code: str, content: str) -> ToolResult:
    return ToolResult(call.id, call.name, False, content, code)


def exception_failure(call: ToolCall, exc: Exception) -> ToolResult:
    code = getattr(exc, "code", None)
    if not isinstance(code, str):
        if isinstance(exc, FileNotFoundError):
            code = "file_not_found"
        elif isinstance(exc, FileExistsError):
            code = "already_exists"
        elif isinstance(exc, UnicodeDecodeError):
            code = "decode_error"
        elif isinstance(exc, ValueError):
            code = "invalid_operation"
        else:
            code = "workspace_failure"
    return failure(call, code, str(exc))
