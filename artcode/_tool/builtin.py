from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
from typing import Any, Awaitable, Callable

from artcode.core.tool import ToolCall, ToolDescriptor, ToolEffect, ToolOrigin, ToolResult, ToolRun
from artcode.core.workspace import IsolationMode, ProcessRequest

from .results import exception_failure, failure, success


@dataclass(frozen=True, slots=True)
class Prepared:
    call: ToolCall
    descriptor: ToolDescriptor
    target: str
    execute: Callable[[], Awaitable[ToolResult]]
    command: str | None = None


def _schema(properties: dict[str, Any], required: list[str]) -> str:
    return json.dumps(
        {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


DESCRIPTORS = (
    ToolDescriptor(
        "read_file", "按范围读取 Workspace 内 UTF-8 文本文件。",
        _schema({"path": {"type": "string"}, "start_line": {"type": "integer"}, "end_line": {"type": "integer"}}, ["path"]),
        ToolEffect.OBSERVE,
    ),
    ToolDescriptor(
        "find_files", "按 glob 查找 Workspace 内文件。",
        _schema({"pattern": {"type": "string"}, "limit": {"type": "integer"}}, ["pattern"]),
        ToolEffect.OBSERVE,
    ),
    ToolDescriptor(
        "search_text", "在 Workspace 内按普通文本搜索。",
        _schema({"query": {"type": "string"}, "glob": {"type": "string"}, "limit": {"type": "integer"}}, ["query"]),
        ToolEffect.OBSERVE,
    ),
    ToolDescriptor(
        "write_file", "创建文本文件，或在明确声明时覆盖。",
        _schema({"path": {"type": "string"}, "content": {"type": "string"}, "overwrite": {"type": "boolean"}}, ["path", "content"]),
        ToolEffect.CHANGE,
    ),
    ToolDescriptor(
        "edit_file", "仅在旧文本唯一匹配时编辑文件。",
        _schema({"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, ["path", "old_text", "new_text"]),
        ToolEffect.CHANGE,
    ),
    ToolDescriptor(
        "run_command", "在当前 Workspace scope 中执行本地 Shell 命令。",
        _schema({"command": {"type": "string"}, "cwd": {"type": "string"}}, ["command"]),
        ToolEffect.CHANGE,
    ),
)


class BuiltinTools:
    def __init__(self, *, command_timeout_seconds: float = 120.0) -> None:
        self.descriptors = DESCRIPTORS
        self._by_name = {item.name: item for item in DESCRIPTORS}
        self.command_timeout_seconds = command_timeout_seconds

    def descriptor(self, name: str) -> ToolDescriptor | None:
        return self._by_name.get(name)

    def prepare(self, call: ToolCall, arguments: dict[str, Any], run: ToolRun) -> Prepared | ToolResult:
        descriptor = self.descriptor(call.name)
        if descriptor is None:
            return failure(call, "tool_not_found", f"未知工具：{call.name}")
        try:
            if call.name == "read_file":
                return self._read(call, descriptor, arguments, run)
            if call.name == "find_files":
                return self._find(call, descriptor, arguments, run)
            if call.name == "search_text":
                return self._search(call, descriptor, arguments, run)
            if call.name == "write_file":
                return self._write(call, descriptor, arguments, run)
            if call.name == "edit_file":
                return self._edit(call, descriptor, arguments, run)
            if call.name == "run_command":
                return self._command(call, descriptor, arguments, run)
        except OSError as exc:
            return exception_failure(call, exc)
        except (TypeError, ValueError) as exc:
            return failure(call, "invalid_arguments", str(exc))
        return failure(call, "tool_not_found", f"未知工具：{call.name}")

    def _read(self, call: ToolCall, descriptor: ToolDescriptor, raw: dict[str, Any], run: ToolRun) -> Prepared:
        _keys(raw, {"path", "start_line", "end_line"}, {"path"})
        path = _text(raw, "path")
        start = _positive_int(raw, "start_line")
        end = _positive_int(raw, "end_line")
        if start is not None and end is not None and end < start:
            raise ValueError("end_line 不能小于 start_line。")
        target = run.workspace.prepare_target(path, must_exist=True)

        async def execute() -> ToolResult:
            try:
                result = await asyncio.to_thread(
                    run.workspace.read_text, target, start_line=start, end_line=end
                )
                content = result.text
                if result.truncated:
                    content += f"\n[内容已截断；next_line={result.next_line}]"
                return success(call, content)
            except Exception as exc:
                return exception_failure(call, exc)

        return Prepared(call, descriptor, _file_target(run, target.path), execute)

    def _find(self, call: ToolCall, descriptor: ToolDescriptor, raw: dict[str, Any], run: ToolRun) -> Prepared:
        _keys(raw, {"pattern", "limit"}, {"pattern"})
        pattern = _text(raw, "pattern")
        limit = _positive_int(raw, "limit") or 1000

        async def execute() -> ToolResult:
            try:
                result = await asyncio.to_thread(run.workspace.find_files, pattern, limit=limit)
                content = "\n".join(result.paths)
                if result.truncated:
                    content += "\n[结果已截断]"
                return success(call, content)
            except Exception as exc:
                return exception_failure(call, exc)

        return Prepared(call, descriptor, f"glob:{pattern}", execute)

    def _search(self, call: ToolCall, descriptor: ToolDescriptor, raw: dict[str, Any], run: ToolRun) -> Prepared:
        _keys(raw, {"query", "glob", "limit"}, {"query"})
        query = _text(raw, "query")
        pattern = raw.get("glob", "**/*")
        if not isinstance(pattern, str) or not pattern:
            raise ValueError("glob 必须是非空字符串。")
        limit = _positive_int(raw, "limit") or 1000

        async def execute() -> ToolResult:
            try:
                result = await asyncio.to_thread(
                    run.workspace.search_text, query, glob=pattern, limit=limit
                )
                content = json.dumps(
                    {
                        "matches": [
                            {"path": item.path, "line": item.line, "text": item.text}
                            for item in result.matches
                        ],
                        "truncated": result.truncated,
                        "skipped_unreadable": result.skipped_unreadable,
                    },
                    ensure_ascii=False,
                )
                return success(call, content)
            except Exception as exc:
                return exception_failure(call, exc)

        return Prepared(call, descriptor, f"search:{pattern}:{query}", execute)

    def _write(self, call: ToolCall, descriptor: ToolDescriptor, raw: dict[str, Any], run: ToolRun) -> Prepared:
        _keys(raw, {"path", "content", "overwrite"}, {"path", "content"})
        path = _text(raw, "path")
        content = raw["content"]
        overwrite = raw.get("overwrite", False)
        if not isinstance(content, str) or not isinstance(overwrite, bool):
            raise ValueError("content 必须是字符串，overwrite 必须是布尔值。")
        target = run.workspace.prepare_target(path, must_exist=False)

        async def execute() -> ToolResult:
            try:
                change = await asyncio.to_thread(
                    run.workspace.write_text, target, content, overwrite=overwrite
                )
                return success(call, f"已写入 {change.path}（{change.bytes_written} bytes）")
            except Exception as exc:
                return exception_failure(call, exc)

        return Prepared(call, descriptor, _file_target(run, target.path), execute)

    def _edit(self, call: ToolCall, descriptor: ToolDescriptor, raw: dict[str, Any], run: ToolRun) -> Prepared:
        _keys(raw, {"path", "old_text", "new_text"}, {"path", "old_text", "new_text"})
        path = _text(raw, "path")
        old_text = raw["old_text"]
        new_text = raw["new_text"]
        if not isinstance(old_text, str) or not old_text or not isinstance(new_text, str):
            raise ValueError("old_text 必须非空且 new_text 必须是字符串。")
        target = run.workspace.prepare_target(path, must_exist=True)

        async def execute() -> ToolResult:
            try:
                change = await asyncio.to_thread(
                    run.workspace.edit_text, target, old_text, new_text
                )
                return success(call, f"已编辑 {change.path}（{change.bytes_written} bytes）")
            except Exception as exc:
                return exception_failure(call, exc)

        return Prepared(call, descriptor, _file_target(run, target.path), execute)

    def _command(self, call: ToolCall, descriptor: ToolDescriptor, raw: dict[str, Any], run: ToolRun) -> Prepared:
        _keys(raw, {"command", "cwd"}, {"command"})
        command = _text(raw, "command").strip()
        cwd = raw.get("cwd", ".")
        if not isinstance(cwd, str) or not cwd.strip():
            raise ValueError("cwd 必须是非空字符串。")
        target = f"{run.workspace.root / cwd}$ {command}"

        async def execute() -> ToolResult:
            try:
                isolation = (
                    IsolationMode.EXPLICIT_UNSAFE
                    if run.permission.shell_policy.value == "explicit_unsafe"
                    else IsolationMode.ENFORCED
                )
                outcome = await run.workspace.run_process(
                    ProcessRequest(
                        argv=("/bin/zsh", "-f", "-c", command),
                        cwd=cwd,
                        timeout_seconds=self.command_timeout_seconds,
                        isolation=isolation,
                    )
                )
                content = (
                    f"exit_code: {outcome.returncode}\nstdout:\n{outcome.stdout}\n"
                    f"stderr:\n{outcome.stderr}"
                )
                if outcome.start_error:
                    return failure(call, "command_error", outcome.start_error)
                if outcome.timed_out:
                    return failure(call, "command_timeout", content)
                if outcome.returncode != 0:
                    return failure(call, "command_failed", content)
                return success(call, content)
            except Exception as exc:
                return exception_failure(call, exc)

        return Prepared(call, descriptor, target, execute, command=command)


def _keys(raw: dict[str, Any], allowed: set[str], required: set[str]) -> None:
    unknown = set(raw) - allowed
    missing = required - set(raw)
    if unknown or missing:
        raise ValueError(f"参数字段不符；缺少 {sorted(missing)}，未知 {sorted(unknown)}")


def _text(raw: dict[str, Any], name: str) -> str:
    value = raw.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} 必须是非空字符串。")
    return value


def _positive_int(raw: dict[str, Any], name: str) -> int | None:
    value = raw.get(name)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} 必须是正整数。")
    return value


def _file_target(run: ToolRun, relative: str) -> str:
    return str((run.workspace.root / relative).resolve(strict=False))
