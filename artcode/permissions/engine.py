from __future__ import annotations

from artcode.security import DangerousCommandValidator

from .models import (
    PermissionAction,
    PermissionDecision,
    PermissionMode,
    PermissionRequest,
    PermissionState,
    RuleSource,
)
from .rules import RuleLoader

READ_ONLY_TOOLS = frozenset({"read_file", "find_files", "search_text"})
WRITE_TOOLS = frozenset({"write_file", "edit_file"})


class PermissionEngine:
    def __init__(
        self,
        rules: RuleLoader,
        dangerous_commands: DangerousCommandValidator,
    ) -> None:
        self.rules = rules
        self.dangerous_commands = dangerous_commands

    def decide(
        self,
        request: PermissionRequest,
        state: PermissionState,
    ) -> PermissionDecision:
        if request.plan_mode and request.tool_name not in READ_ONLY_TOOLS:
            return PermissionDecision(
                PermissionAction.DENY,
                RuleSource.PLAN,
                "Plan 状态只允许读取文件、查找文件和搜索文本",
            )

        if request.tool_name == "run_command":
            hit = self.dangerous_commands.check(request.target, request.workspace)
            if hit is not None:
                return PermissionDecision(
                    PermissionAction.DENY,
                    RuleSource.DANGEROUS_COMMAND,
                    f"{hit.rule_id}：{hit.reason}",
                )

        match = self.rules.query(request.tool_name, request.target)
        if match is not None:
            return PermissionDecision(
                match.action,
                match.source,
                f"{match.source.value} 规则第 {match.index} 条",
                rule_index=match.index,
                rule_file=match.path,
            )

        if request.tool_name == "run_command":
            return PermissionDecision(
                state.shell_policy.default_action,
                RuleSource.SHELL_POLICY,
                f"Shell 策略：{state.shell_policy.value}",
            )
        if request.tool_name in READ_ONLY_TOOLS | WRITE_TOOLS:
            return PermissionDecision(
                state.mode.default_for(request.tool_name),
                RuleSource.MODE,
                f"权限模式：{state.mode.value}",
            )
        return PermissionDecision(
            PermissionAction.DENY,
            RuleSource.MODE,
            f"未知工具：{request.tool_name}",
        )
