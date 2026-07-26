from __future__ import annotations

import glob
import json
from pathlib import Path
from typing import Any

from .base import PreparedToolCall, ToolExecutionContext, ToolPreview
from .results import ToolResult, error_result, success_result


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
        else code
    )
    return error_result(tool_name, error_code, str(exc))


class ReadFileTool:
    name = "read_file"
    description = (
        "读取允许目录内的 UTF-8 文本文件，可选按行范围读取。"
        "用于理解代码、查看配置、获取编辑前上下文；修改已有文件前应先用本工具读取目标文件或相关片段。"
    )
    requires_confirmation = False
    parameters_schema = _schema(
        {
            "path": {"type": "string", "description": "要读取的文件路径。"},
            "start_line": {"type": "integer", "description": "可选，起始行号，1 起算。"},
            "end_line": {"type": "integer", "description": "可选，结束行号，包含该行。"},
        },
        ["path"],
    )

    def prepare(self, arguments: dict[str, Any], context: ToolExecutionContext) -> PreparedToolCall | ToolResult:
        try:
            path = context.path_policy.resolve_existing_path(_string_arg(arguments, "path"), context.default_cwd)
            start_line = _optional_int_arg(arguments, "start_line")
            end_line = _optional_int_arg(arguments, "end_line")
            if start_line is not None and end_line is not None and end_line < start_line:
                raise ValueError("参数 end_line 必须大于等于 start_line。")
        except Exception as exc:
            return _prepare_error(self.name, exc)

        return PreparedToolCall(
            tool=self,
            arguments={"path": path, "start_line": start_line, "end_line": end_line},
            preview=ToolPreview(self.name, f"读取文件 {path}", _target(context, path), False),
        )

    async def execute(self, prepared: PreparedToolCall, context: ToolExecutionContext) -> ToolResult:
        path: Path = prepared.arguments["path"]
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return error_result(self.name, "file_not_found", f"文件不存在：{path}")
        except UnicodeDecodeError:
            return error_result(self.name, "decode_error", f"文件不是可读取的 UTF-8 文本：{path}")
        except OSError as exc:
            return error_result(self.name, "read_error", f"读取文件失败：{exc}")

        start_line = prepared.arguments["start_line"]
        end_line = prepared.arguments["end_line"]
        if start_line is not None or end_line is not None:
            lines = text.splitlines(keepends=True)
            start = (start_line or 1) - 1
            end = end_line if end_line is not None else len(lines)
            text = "".join(lines[start:end])

        return success_result(self.name, f"已读取文件：{path}", text, context.max_result_bytes)


class WriteFileTool:
    name = "write_file"
    description = (
        "在允许目录内创建或覆盖完整 UTF-8 文本文件，默认不覆盖已有文件。"
        "适合写入新文件或整文件生成；覆盖已有文件前必须确认意图，避免用它做小范围替换。"
    )
    requires_confirmation = True
    parameters_schema = _schema(
        {
            "path": {"type": "string", "description": "要写入的文件路径。"},
            "content": {"type": "string", "description": "要写入的 UTF-8 文本内容。"},
            "overwrite": {"type": "boolean", "description": "是否允许覆盖已有文件，默认 false。"},
        },
        ["path", "content"],
    )

    def prepare(self, arguments: dict[str, Any], context: ToolExecutionContext) -> PreparedToolCall | ToolResult:
        try:
            path = context.path_policy.resolve_new_file_path(_string_arg(arguments, "path"), context.default_cwd)
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
            arguments={"path": path, "content": content, "overwrite": overwrite},
            preview=ToolPreview(self.name, f"{action}文件 {path}", _target(context, path), True),
        )

    async def execute(self, prepared: PreparedToolCall, context: ToolExecutionContext) -> ToolResult:
        path: Path = prepared.arguments["path"]
        content: str = prepared.arguments["content"]
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        except OSError as exc:
            return error_result(self.name, "write_error", f"写入文件失败：{exc}")
        return success_result(self.name, f"已写入文件：{path}", f"path: {path}", context.max_result_bytes)


class EditFileTool:
    name = "edit_file"
    description = (
        "在允许目录内对 UTF-8 文本文件执行严格原文唯一匹配替换。"
        "编辑前必须先读取目标文件或相关上下文；old_text 必须来自实际文件内容，并且应唯一匹配。"
        "适合小范围精确修改，不适合整文件重写。"
    )
    requires_confirmation = True
    parameters_schema = _schema(
        {
            "path": {"type": "string", "description": "要修改的文件路径。"},
            "old_text": {"type": "string", "description": "必须唯一匹配的原文。"},
            "new_text": {"type": "string", "description": "替换后的新文本。"},
        },
        ["path", "old_text", "new_text"],
    )

    def prepare(self, arguments: dict[str, Any], context: ToolExecutionContext) -> PreparedToolCall | ToolResult:
        try:
            path = context.path_policy.resolve_existing_path(_string_arg(arguments, "path"), context.default_cwd)
            old_text = _string_arg(arguments, "old_text")
            new_text = arguments.get("new_text")
            if not isinstance(new_text, str):
                raise ValueError("参数 new_text 必须是字符串。")
        except Exception as exc:
            return _prepare_error(self.name, exc)

        return PreparedToolCall(
            tool=self,
            arguments={"path": path, "old_text": old_text, "new_text": new_text},
            preview=ToolPreview(self.name, f"修改文件 {path}", _target(context, path), True),
        )

    async def execute(self, prepared: PreparedToolCall, context: ToolExecutionContext) -> ToolResult:
        path: Path = prepared.arguments["path"]
        old_text: str = prepared.arguments["old_text"]
        new_text: str = prepared.arguments["new_text"]
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return error_result(self.name, "file_not_found", f"文件不存在：{path}")
        except UnicodeDecodeError:
            return error_result(self.name, "decode_error", f"文件不是可读取的 UTF-8 文本：{path}")
        except OSError as exc:
            return error_result(self.name, "read_error", f"读取文件失败：{exc}")

        count = text.count(old_text)
        if count == 0:
            return error_result(self.name, "old_text_not_found", "没有找到要替换的原文，文件未修改。")
        if count > 1:
            return error_result(self.name, "old_text_not_unique", f"原文匹配了 {count} 次，文件未修改。")

        try:
            path.write_text(text.replace(old_text, new_text, 1), encoding="utf-8")
        except OSError as exc:
            return error_result(self.name, "write_error", f"写入文件失败：{exc}")
        return success_result(self.name, f"已修改文件：{path}", f"path: {path}", context.max_result_bytes)


class FindFilesTool:
    name = "find_files"
    description = (
        "按 glob 模式查找允许目录内的文件。"
        "用于定位候选文件，优先于 shell find；找到文件后通常再配合 read_file 或 search_text 理解内容。"
    )
    requires_confirmation = False
    parameters_schema = _schema(
        {
            "pattern": {"type": "string", "description": "glob 文件匹配模式，例如 **/*.py。"},
        },
        ["pattern"],
    )

    def prepare(self, arguments: dict[str, Any], context: ToolExecutionContext) -> PreparedToolCall | ToolResult:
        try:
            pattern = _string_arg(arguments, "pattern")
        except Exception as exc:
            return _prepare_error(self.name, exc)
        return PreparedToolCall(
            tool=self,
            arguments={"pattern": pattern},
            preview=ToolPreview(self.name, f"查找文件 {pattern}", ".", False),
        )

    async def execute(self, prepared: PreparedToolCall, context: ToolExecutionContext) -> ToolResult:
        pattern: str = prepared.arguments["pattern"]
        matches: list[str] = []

        if Path(pattern).is_absolute():
            candidates = (Path(path) for path in glob.glob(pattern, recursive=True))
        else:
            candidates = (path for root in context.path_policy.allowed_roots for path in root.glob(pattern))

        for candidate in candidates:
            try:
                resolved = candidate.resolve()
            except OSError:
                continue
            if resolved.is_file() and context.path_policy.is_allowed(resolved):
                matches.append(str(resolved))

        content = "\n".join(sorted(set(matches)))
        return success_result(self.name, f"找到 {len(set(matches))} 个匹配文件。", content, context.max_result_bytes)


class SearchTextTool:
    name = "search_text"
    description = (
        "在允许目录内按普通文本搜索 UTF-8 文本文件内容。"
        "用于查找符号、配置、错误文本或相关上下文，优先于 shell grep；修改前可用它定位需要读取的片段。"
    )
    requires_confirmation = False
    parameters_schema = _schema(
        {
            "query": {"type": "string", "description": "要搜索的普通文本。"},
            "path": {"type": "string", "description": "可选，搜索的文件或目录，默认所有允许目录。"},
        },
        ["query"],
    )

    def prepare(self, arguments: dict[str, Any], context: ToolExecutionContext) -> PreparedToolCall | ToolResult:
        try:
            query = _string_arg(arguments, "query")
            raw_path = arguments.get("path")
            path = None
            if raw_path is not None:
                if not isinstance(raw_path, str) or not raw_path.strip():
                    raise ValueError("参数 path 必须是非空字符串。")
                path = context.path_policy.resolve_existing_path(raw_path, context.default_cwd)
        except Exception as exc:
            return _prepare_error(self.name, exc)

        target = _target(context, path) if path is not None else "."
        return PreparedToolCall(
            tool=self,
            arguments={"query": query, "path": path},
            preview=ToolPreview(self.name, f"搜索文本 {query}", target, False),
        )

    async def execute(self, prepared: PreparedToolCall, context: ToolExecutionContext) -> ToolResult:
        query: str = prepared.arguments["query"]
        path: Path | None = prepared.arguments["path"]
        files = _iter_search_files(path, context)
        matches: list[dict[str, Any]] = []
        skipped = 0

        for file_path in files:
            try:
                lines = file_path.read_text(encoding="utf-8").splitlines()
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
        return success_result(self.name, f"找到 {len(matches)} 处匹配。", content, context.max_result_bytes)


def _iter_search_files(path: Path | None, context: ToolExecutionContext) -> list[Path]:
    roots = [path] if path is not None else list(context.path_policy.allowed_roots)
    files: list[Path] = []
    for root in roots:
        if root.is_file() and context.path_policy.is_allowed(root):
            files.append(root)
        elif root.is_dir() and context.path_policy.is_allowed(root):
            for candidate in root.rglob("*"):
                try:
                    if candidate.is_file() and context.path_policy.is_allowed(candidate.resolve()):
                        files.append(candidate.resolve())
                except OSError:
                    continue
    return files


def _target(context: ToolExecutionContext, path: Path) -> str:
    relative_target = getattr(context.path_policy, "relative_target", None)
    if callable(relative_target):
        return relative_target(path)
    return str(path)
