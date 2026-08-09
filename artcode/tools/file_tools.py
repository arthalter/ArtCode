from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .base import (
    DescriptorBackedTool,
    PreparedToolCall,
    ToolDescriptor,
    ToolEffect,
    ToolPreview,
    ToolRunContext,
)
from .results import ToolResult, error_result, success_result
from .filesystem import (
    AtomicWriteError,
    FileTargetSnapshot,
    TargetChangedError,
    WorkspaceFileAccess,
    WorkspaceFileError,
)
from artcode.context_management.estimator import estimate_text_tokens
from artcode.context_management.models import SINGLE_TOOL_RESULT_TOKENS


def _schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _string_arg(arguments: dict[str, Any], name: str) -> str:
    value = arguments.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"参数 {name} 必须是非空字符串。")
    return value


def _optional_int_arg(arguments: dict[str, Any], name: str) -> int | None:
    value = arguments.get(name)
    if value is None:
        return None
    if not isinstance(value, int):
        raise ValueError(f"参数 {name} 必须是整数。")
    if value < 1:
        raise ValueError(f"参数 {name} 必须大于等于 1。")
    return value


def _bool_arg(arguments: dict[str, Any], name: str, default: bool = False) -> bool:
    value = arguments.get(name, default)
    if not isinstance(value, bool):
        raise ValueError(f"参数 {name} 必须是布尔值。")
    return value


def _prepare_error(tool_name: str, exc: Exception, code: str = "invalid_arguments") -> ToolResult:
    text = str(exc)
    error_code = (
        "path_outside_workspace"
        if "Workspace 外" in text
        else "path_outside_allowed_dirs"
        if "不在允许目录" in text
        else "sensitive_path"
        if "敏感路径" in text
        else exc.error_code
        if isinstance(exc, WorkspaceFileError)
        else code
    )
    return error_result(tool_name, error_code, str(exc))


class ReadFileTool(DescriptorBackedTool):
    descriptor = ToolDescriptor(
        name="read_file",
        description=(
            "读取允许目录内的 UTF-8 文本文件，可选按行范围读取。"
            "用于理解代码、查看配置、获取编辑前上下文；修改已有文件前应先用本工具读取目标文件或相关片段。"
        ),
        parameters_schema=_schema(
            {
                "path": {"type": "string", "description": "要读取的文件路径。"},
                "start_line": {"type": "integer", "description": "可选，起始行号，1 起算。"},
                "end_line": {"type": "integer", "description": "可选，结束行号，包含该行。"},
            },
            ["path"],
        ),
        effect=ToolEffect.READ,
    )

    def prepare(self, arguments: dict[str, Any], context: ToolRunContext) -> PreparedToolCall | ToolResult:
        try:
            access = WorkspaceFileAccess(context.path_policy)
            target = access.prepare_existing(
                _string_arg(arguments, "path"),
                context.default_cwd,
            )
            path = target.approved_path
            start_line = _optional_int_arg(arguments, "start_line")
            end_line = _optional_int_arg(arguments, "end_line")
            if start_line is not None and end_line is not None and end_line < start_line:
                raise ValueError("参数 end_line 必须大于等于 start_line。")
        except Exception as exc:
            return _prepare_error(self.name, exc)

        artifact_store = context.artifact_store
        is_artifact = bool(
            artifact_store is not None
            and artifact_store.is_current_artifact(path)
        )
        if is_artifact and (start_line is None or end_line is None):
            return error_result(
                self.name,
                "artifact_range_required",
                "读取当前会话的存盘结果时，必须同时提供 start_line 和 end_line。",
            )

        return PreparedToolCall(
            tool=self,
            arguments={
                "path": path,
                "target": target,
                "start_line": start_line,
                "end_line": end_line,
                "is_artifact": is_artifact,
            },
            preview=ToolPreview(self.name, f"读取文件 {path}", _target(context, path), False),
        )

    async def execute(self, prepared: PreparedToolCall, context: ToolRunContext) -> ToolResult:
        path: Path = prepared.arguments["path"]
        try:
            text = WorkspaceFileAccess(context.path_policy).read_text(
                prepared.arguments["target"]
            )
        except FileNotFoundError:
            return error_result(self.name, "file_not_found", f"文件不存在：{path}")
        except UnicodeDecodeError:
            return error_result(self.name, "decode_error", f"文件不是可读取的 UTF-8 文本：{path}")
        except TargetChangedError as exc:
            return error_result(self.name, exc.error_code, str(exc))
        except OSError as exc:
            return error_result(self.name, "read_error", f"读取文件失败：{exc}")

        start_line = prepared.arguments["start_line"]
        end_line = prepared.arguments["end_line"]
        if start_line is not None or end_line is not None:
            lines = text.splitlines(keepends=True)
            start = (start_line or 1) - 1
            end = end_line if end_line is not None else len(lines)
            text = "".join(lines[start:end])

        if prepared.arguments.get("is_artifact") and estimate_text_tokens(text) > SINGLE_TOOL_RESULT_TOKENS:
            return error_result(
                self.name,
                "artifact_range_too_large",
                "选定的存盘结果片段超过 8,000 Token，请缩小行范围。",
            )

        return success_result(self.name, f"已读取文件：{path}", text)


class WriteFileTool(DescriptorBackedTool):
    descriptor = ToolDescriptor(
        name="write_file",
        description=(
            "在允许目录内创建或覆盖完整 UTF-8 文本文件，默认不覆盖已有文件。"
            "适合写入新文件或整文件生成；覆盖已有文件前必须确认意图，避免用它做小范围替换。"
        ),
        parameters_schema=_schema(
            {
                "path": {"type": "string", "description": "要写入的文件路径。"},
                "content": {"type": "string", "description": "要写入的 UTF-8 文本内容。"},
                "overwrite": {"type": "boolean", "description": "是否允许覆盖已有文件，默认 false。"},
            },
            ["path", "content"],
        ),
        effect=ToolEffect.WRITE,
    )

    def prepare(self, arguments: dict[str, Any], context: ToolRunContext) -> PreparedToolCall | ToolResult:
        try:
            access = WorkspaceFileAccess(context.path_policy)
            target = access.prepare_file(
                _string_arg(arguments, "path"),
                context.default_cwd,
            )
            path = target.approved_path
            content = arguments.get("content")
            if not isinstance(content, str):
                raise ValueError("参数 content 必须是字符串。")
            overwrite = _bool_arg(arguments, "overwrite")
        except Exception as exc:
            return _prepare_error(self.name, exc)

        if path.exists() and not overwrite:
            return error_result(self.name, "already_exists", f"文件已存在，且未声明覆盖：{path}")

        action = "覆盖" if path.exists() else "写入"
        return PreparedToolCall(
            tool=self,
            arguments={
                "path": path,
                "target": target,
                "content": content,
                "overwrite": overwrite,
            },
            preview=ToolPreview(self.name, f"{action}文件 {path}", _target(context, path), True),
        )

    async def execute(self, prepared: PreparedToolCall, context: ToolRunContext) -> ToolResult:
        path: Path = prepared.arguments["path"]
        content: str = prepared.arguments["content"]
        try:
            WorkspaceFileAccess(context.path_policy).atomic_write_text(
                prepared.arguments["target"],
                content,
                overwrite=prepared.arguments["overwrite"],
            )
        except FileExistsError:
            return error_result(self.name, "already_exists", f"文件已存在，且未声明覆盖：{path}")
        except TargetChangedError as exc:
            return error_result(self.name, exc.error_code, str(exc))
        except AtomicWriteError as exc:
            return error_result(self.name, exc.error_code, str(exc))
        except OSError as exc:
            return error_result(self.name, "write_error", f"写入文件失败：{exc}")
        return success_result(self.name, f"已写入文件：{path}", f"path: {path}")


class EditFileTool(DescriptorBackedTool):
    descriptor = ToolDescriptor(
        name="edit_file",
        description=(
            "在允许目录内对 UTF-8 文本文件执行严格原文唯一匹配替换。"
            "编辑前必须先读取目标文件或相关上下文；old_text 必须来自实际文件内容，并且应唯一匹配。"
            "适合小范围精确修改，不适合整文件重写。"
        ),
        parameters_schema=_schema(
            {
                "path": {"type": "string", "description": "要修改的文件路径。"},
                "old_text": {"type": "string", "description": "必须唯一匹配的原文。"},
                "new_text": {"type": "string", "description": "替换后的新文本。"},
            },
            ["path", "old_text", "new_text"],
        ),
        effect=ToolEffect.WRITE,
    )

    def prepare(self, arguments: dict[str, Any], context: ToolRunContext) -> PreparedToolCall | ToolResult:
        try:
            access = WorkspaceFileAccess(context.path_policy)
            target = access.prepare_existing(
                _string_arg(arguments, "path"),
                context.default_cwd,
            )
            path = target.approved_path
            old_text = _string_arg(arguments, "old_text")
            new_text = arguments.get("new_text")
            if not isinstance(new_text, str):
                raise ValueError("参数 new_text 必须是字符串。")
        except Exception as exc:
            return _prepare_error(self.name, exc)

        return PreparedToolCall(
            tool=self,
            arguments={
                "path": path,
                "target": target,
                "old_text": old_text,
                "new_text": new_text,
            },
            preview=ToolPreview(self.name, f"修改文件 {path}", _target(context, path), True),
        )

    async def execute(self, prepared: PreparedToolCall, context: ToolRunContext) -> ToolResult:
        path: Path = prepared.arguments["path"]
        old_text: str = prepared.arguments["old_text"]
        new_text: str = prepared.arguments["new_text"]
        access = WorkspaceFileAccess(context.path_policy)
        try:
            text = access.read_text(prepared.arguments["target"])
        except FileNotFoundError:
            return error_result(self.name, "file_not_found", f"文件不存在：{path}")
        except UnicodeDecodeError:
            return error_result(self.name, "decode_error", f"文件不是可读取的 UTF-8 文本：{path}")
        except TargetChangedError as exc:
            return error_result(self.name, exc.error_code, str(exc))
        except OSError as exc:
            return error_result(self.name, "read_error", f"读取文件失败：{exc}")

        count = text.count(old_text)
        if count == 0:
            return error_result(self.name, "old_text_not_found", "没有找到要替换的原文，文件未修改。")
        if count > 1:
            return error_result(self.name, "old_text_not_unique", f"原文匹配了 {count} 次，文件未修改。")

        try:
            access.atomic_write_text(
                prepared.arguments["target"],
                text.replace(old_text, new_text, 1),
                overwrite=True,
            )
        except TargetChangedError as exc:
            return error_result(self.name, exc.error_code, str(exc))
        except AtomicWriteError as exc:
            return error_result(self.name, exc.error_code, str(exc))
        except OSError as exc:
            return error_result(self.name, "write_error", f"写入文件失败：{exc}")
        return success_result(self.name, f"已修改文件：{path}", f"path: {path}")


class FindFilesTool(DescriptorBackedTool):
    descriptor = ToolDescriptor(
        name="find_files",
        description=(
            "按 glob 模式查找允许目录内的文件。"
            "用于定位候选文件，优先于 shell find；找到文件后通常再配合 read_file 或 search_text 理解内容。"
        ),
        parameters_schema=_schema(
            {
                "pattern": {"type": "string", "description": "glob 文件匹配模式，例如 **/*.py。"},
            },
            ["pattern"],
        ),
        effect=ToolEffect.READ,
    )

    def prepare(self, arguments: dict[str, Any], context: ToolRunContext) -> PreparedToolCall | ToolResult:
        try:
            pattern = _string_arg(arguments, "pattern")
        except Exception as exc:
            return _prepare_error(self.name, exc)
        return PreparedToolCall(
            tool=self,
            arguments={"pattern": pattern},
            preview=ToolPreview(self.name, f"查找文件 {pattern}", ".", False),
        )

    async def execute(self, prepared: PreparedToolCall, context: ToolRunContext) -> ToolResult:
        pattern: str = prepared.arguments["pattern"]
        matches = [
            str(path)
            for path in WorkspaceFileAccess(context.path_policy).find_files(pattern)
        ]

        content = "\n".join(sorted(set(matches)))
        return success_result(self.name, f"找到 {len(set(matches))} 个匹配文件。", content)


class SearchTextTool(DescriptorBackedTool):
    descriptor = ToolDescriptor(
        name="search_text",
        description=(
            "在允许目录内按普通文本搜索 UTF-8 文本文件内容。"
            "用于查找符号、配置、错误文本或相关上下文，优先于 shell grep；修改前可用它定位需要读取的片段。"
        ),
        parameters_schema=_schema(
            {
                "query": {"type": "string", "description": "要搜索的普通文本。"},
                "path": {"type": "string", "description": "可选，搜索的文件或目录，默认所有允许目录。"},
            },
            ["query"],
        ),
        effect=ToolEffect.READ,
    )

    def prepare(self, arguments: dict[str, Any], context: ToolRunContext) -> PreparedToolCall | ToolResult:
        try:
            query = _string_arg(arguments, "query")
            raw_path = arguments.get("path")
            target: FileTargetSnapshot | None = None
            if raw_path is not None:
                if not isinstance(raw_path, str) or not raw_path.strip():
                    raise ValueError("参数 path 必须是非空字符串。")
                target = WorkspaceFileAccess(context.path_policy).prepare_existing(
                    raw_path,
                    context.default_cwd,
                )
        except Exception as exc:
            return _prepare_error(self.name, exc)

        display_target = target.display_target if target is not None else "."
        return PreparedToolCall(
            tool=self,
            arguments={"query": query, "target": target},
            preview=ToolPreview(self.name, f"搜索文本 {query}", display_target, False),
        )

    async def execute(self, prepared: PreparedToolCall, context: ToolRunContext) -> ToolResult:
        query: str = prepared.arguments["query"]
        access = WorkspaceFileAccess(context.path_policy)
        try:
            files = access.search_files(
                prepared.arguments["target"]
            )
        except TargetChangedError as exc:
            return error_result(self.name, exc.error_code, str(exc))
        matches: list[dict[str, Any]] = []
        skipped = 0

        for file_path in files:
            try:
                lines = access.read_current_text(file_path).splitlines()
            except UnicodeDecodeError:
                skipped += 1
                continue
            except OSError:
                continue
            for line_number, line in enumerate(lines, start=1):
                if query in line:
                    matches.append(
                        {
                            "path": str(file_path),
                            "line": line_number,
                            "text": line.strip(),
                        }
                    )

        payload = {"matches": matches, "skipped_unreadable_files": skipped}
        content = json.dumps(payload, ensure_ascii=False, indent=2)
        return success_result(self.name, f"找到 {len(matches)} 处匹配。", content)


def _target(context: ToolRunContext, path: Path) -> str:
    return WorkspaceFileAccess(context.path_policy).display_target(path)
