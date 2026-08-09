from __future__ import annotations

import os
import re
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
from .policy import AllowedPathPolicy
from .results import ToolResult, error_result, success_result
from .process import ProcessSupervisor


class RunCommandTool(DescriptorBackedTool):
    descriptor = ToolDescriptor(
        name="run_command",
        description=(
            "在允许目录内执行一段 shell 命令。"
            "命令始终视为有副作用工具，应谨慎使用；已有 read_file、find_files、search_text、write_file 或 edit_file "
            "等专用工具能完成时，优先使用专用工具，不要用 shell 命令替代。"
        ),
        parameters_schema={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "要执行的 shell 命令。"},
                "cwd": {"type": "string", "description": "可选，命令工作目录。"},
            },
            "required": ["command"],
            "additionalProperties": False,
        },
        effect=ToolEffect.SHELL,
    )

    def __init__(self, supervisor: ProcessSupervisor | None = None) -> None:
        self.supervisor = supervisor or ProcessSupervisor()

    def prepare(self, arguments: dict[str, Any], context: ToolRunContext) -> PreparedToolCall | ToolResult:
        command = arguments.get("command")
        if not isinstance(command, str) or not command.strip():
            return error_result(self.name, "invalid_arguments", "参数 command 必须是非空字符串。")
        command = command.strip()

        cwd_result = _resolve_cwd(arguments.get("cwd"), context)
        if isinstance(cwd_result, ToolResult):
            return cwd_result
        cwd = cwd_result

        # ch05 compatibility tests still exercise the old policy directly.
        # The ch06 runtime uses WorkspacePathPolicy and delegates hard command
        # checks to PermissionEngine before any process is started.
        if isinstance(context.path_policy, AllowedPathPolicy):
            dangerous = validate_shell_command(command, context.path_policy)
            if dangerous is not None:
                return dangerous

        return PreparedToolCall(
            tool=self,
            arguments={"command": command, "cwd": cwd},
            preview=ToolPreview(self.name, f"执行命令：{command}", f"{cwd}$ {command}", True),
        )

    async def execute(self, prepared: PreparedToolCall, context: ToolRunContext) -> ToolResult:
        command: str = prepared.arguments["command"]
        cwd: Path = prepared.arguments["cwd"]
        argv = ["/bin/zsh", "-f", "-c", command]
        state = context.permission_state
        shell_policy = state.shell_policy if state is not None else context.shell_policy
        if shell_policy.uses_sandbox:
            if context.seatbelt is None:
                return error_result(self.name, "sandbox_error", "Seatbelt 未初始化，拒绝执行命令。")
            try:
                argv = [*context.seatbelt.command_prefix(), *argv]
            except Exception as exc:
                return error_result(self.name, "sandbox_error", str(exc))
        environment = _safe_environment(context)
        result = await self.supervisor.run(
            argv,
            cwd,
            environment,
            context.command_timeout_seconds,
        )
        if result.start_error is not None:
            return error_result(
                self.name,
                "command_error",
                f"命令执行失败：{result.start_error}",
            )
        if result.timed_out:
            return error_result(
                self.name,
                "command_timeout",
                f"命令超过 {int(context.command_timeout_seconds)} 秒未结束。",
            )

        stdout = result.stdout.decode("utf-8", errors="replace")
        stderr = result.stderr.decode("utf-8", errors="replace")
        content = "\n".join(
            [
                f"exit_code: {result.returncode}",
                "stdout:",
                stdout,
                "stderr:",
                stderr,
            ]
        )
        if result.returncode == 0:
            return success_result(self.name, "命令执行成功。", content)
        return error_result(
            self.name,
            "command_failed",
            f"命令退出码为 {result.returncode}。",
            content,
        )


def validate_shell_command(command: str, policy: AllowedPathPolicy) -> ToolResult | None:
    lowered = command.lower()
    if re.search(r"(^|[;&|]\s*)sudo(\s|$)", lowered):
        return error_result("run_command", "dangerous_command", "ch03 不允许执行 sudo 命令。")
    if "rm -rf /" in lowered or "rm -fr /" in lowered or re.search(r"\brm\s+-[^\s]*[rf][^\s]*\s+/\s*($|[;&|])", lowered):
        return error_result("run_command", "dangerous_command", "拒绝执行明显危险的删除命令。")
    if ":(){" in lowered:
        return error_result("run_command", "dangerous_command", "拒绝执行明显危险的 shell 函数命令。")

    for redirected_path in re.findall(r"(?:^|\s)(?:>|>>)\s*(/[^\s;&|]+)", command):
        if not policy.is_allowed(Path(redirected_path)):
            return error_result("run_command", "dangerous_command", f"拒绝重定向写入允许目录外路径：{redirected_path}")
    return None


def _resolve_cwd(raw_cwd: Any, context: ToolRunContext) -> Path | ToolResult:
    if raw_cwd is None:
        return context.default_cwd or context.path_policy.allowed_roots[0]
    if not isinstance(raw_cwd, str) or not raw_cwd.strip():
        return error_result("run_command", "invalid_arguments", "参数 cwd 必须是非空字符串。")
    try:
        cwd = context.path_policy.resolve_existing_path(raw_cwd, context.default_cwd)
    except Exception as exc:
        code = "path_outside_allowed_dirs" if "不在允许目录" in str(exc) else "invalid_arguments"
        return error_result("run_command", code, str(exc))
    if not cwd.is_dir():
        return error_result("run_command", "invalid_arguments", f"cwd 不是目录：{cwd}")
    return cwd


def _safe_environment(context: ToolRunContext) -> dict[str, str]:
    allowed = ("PATH", "LANG", "LC_ALL", "TERM")
    environment = {key: os.environ[key] for key in allowed if key in os.environ}
    environment.setdefault("PATH", "/usr/bin:/bin:/usr/sbin:/sbin")
    environment["HOME"] = str(Path.home())
    if context.seatbelt is not None and context.seatbelt.temp_dir is not None:
        environment["TMPDIR"] = str(context.seatbelt.temp_dir)
    else:
        environment["TMPDIR"] = os.environ.get("TMPDIR", "/tmp")
    return environment
