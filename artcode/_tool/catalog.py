from __future__ import annotations

import asyncio
import json
from pathlib import Path
import uuid

from artcode.core.tool import (
    ApprovalChoice,
    ApprovalRequest,
    Approver,
    McpLoading,
    McpReport,
    McpServerApprover,
    McpToolHit,
    PermissionMode,
    PermissionSnapshot,
    RunMode,
    ShellPolicy,
    ToolCall,
    ToolDescriptor,
    ToolEffect,
    ToolOrigin,
    ToolResult,
    ToolRun,
    ToolSource,
)

from .batch import execute_ordered_batches
from .builtin import BuiltinTools, Prepared
from .mcp import McpAdapter
from .permissions import PermissionStore
from .policy import DangerousCommands, explicit_rule, mode_action
from .results import failure
from .subagent_adapter import SubagentToolAdapter


class LocalTools:
    def __init__(
        self,
        *,
        permission_mode: PermissionMode = PermissionMode.DEFAULT,
        shell_policy: ShellPolicy = ShellPolicy.SANDBOX_AUTO,
        rules_path: Path | None = None,
        command_timeout_seconds: float = 120.0,
        tool_timeout_seconds: float = 120.0,
        mcp_tool_timeout_seconds: float = 60.0,
    ) -> None:
        if not isinstance(permission_mode, PermissionMode) or not isinstance(shell_policy, ShellPolicy):
            raise TypeError("permission_mode and shell_policy must use Tool enums")
        self._id = uuid.uuid4().hex
        if tool_timeout_seconds <= 0:
            raise ValueError("tool_timeout_seconds 必须为正数。")
        self._tool_timeout_seconds = tool_timeout_seconds
        self._builtin = BuiltinTools(command_timeout_seconds=command_timeout_seconds)
        self._descriptors = {item.name: item for item in self._builtin.descriptors}
        self._permission = PermissionStore(
            mode=permission_mode, shell_policy=shell_policy, path=rules_path
        )
        self._dangerous = DangerousCommands(Path(__file__).with_name("dangerous_commands.yml"))
        self._mcp_tool_timeout_seconds = mcp_tool_timeout_seconds
        self._mcp: McpAdapter | None = None
        self._control: SubagentToolAdapter | None = None
        self._closed = False

    def register_subagents(self, subagents) -> None:
        self._ensure_open()
        if self._control is not None:
            raise RuntimeError("Subagent Tool Adapter 已注册。")
        self._control = SubagentToolAdapter(subagents)
        self._descriptors.update(
            (item.name, item) for item in self._control.descriptors
        )

    async def start_mcp(
        self,
        workspace,
        user_config,
        project_config,
        *,
        loading: McpLoading = McpLoading.EAGER,
        approver: McpServerApprover | None = None,
    ) -> McpReport:
        self._ensure_open()
        if self._mcp is not None:
            raise RuntimeError("MCP 已经启动。")
        self._mcp = McpAdapter(
            str(workspace.root), tool_timeout=self._mcp_tool_timeout_seconds
        )
        report = await self._mcp.start(
            user_config, project_config, loading=loading, approver=approver
        )
        self._descriptors.update(
            (item.name, item) for item in self._mcp.all_descriptors
        )
        return report

    def search_mcp(self, query: str, *, limit: int = 5) -> tuple[McpToolHit, ...]:
        self._ensure_open()
        return () if self._mcp is None else self._mcp.search(query, limit=limit)

    def activate_mcp(self, name: str) -> bool:
        self._ensure_open()
        return False if self._mcp is None else self._mcp.activate(name)

    def open_run(
        self,
        workspace,
        mode: RunMode,
        *,
        source: ToolSource = ToolSource.MAIN,
        allowed_tools: frozenset[str] | None = None,
    ) -> ToolRun:
        self._ensure_open()
        if not isinstance(mode, RunMode) or not isinstance(source, ToolSource):
            raise TypeError("mode/source 类型无效。")
        descriptors: list[ToolDescriptor] = []
        for descriptor in self._builtin.descriptors:
            if mode is RunMode.PLAN and (
                descriptor.origin is not ToolOrigin.BUILTIN
                or descriptor.effect is not ToolEffect.OBSERVE
            ):
                continue
            if source is ToolSource.SUBAGENT and not descriptor.subagent_allowed:
                continue
            if allowed_tools is not None and descriptor.name not in allowed_tools:
                continue
            descriptors.append(descriptor)
        if self._mcp is not None and mode is not RunMode.PLAN:
            for descriptor in self._mcp.active_descriptors:
                if source is ToolSource.SUBAGENT and not descriptor.subagent_allowed:
                    continue
                if allowed_tools is not None and descriptor.name not in allowed_tools:
                    continue
                descriptors.append(descriptor)
        if self._control is not None and mode is not RunMode.PLAN and source is ToolSource.MAIN:
            for descriptor in self._control.descriptors:
                if allowed_tools is not None and descriptor.name not in allowed_tools:
                    continue
                descriptors.append(descriptor)
        return ToolRun(
            tuple(descriptors),
            mode,
            source,
            self._permission.snapshot(),
            workspace,
            self._id,
            allowed_tools,
        )

    async def execute_batch(
        self,
        run: ToolRun,
        calls: tuple[ToolCall, ...],
        *,
        approver: Approver | None = None,
    ) -> tuple[ToolResult, ...]:
        self._ensure_open()
        if not isinstance(run, ToolRun) or run.catalog_id != self._id:
            raise ValueError("Tool Run 快照不属于当前 Tool 模块。")
        if not isinstance(calls, tuple) or not all(isinstance(call, ToolCall) for call in calls):
            raise TypeError("calls 必须是 ToolCall tuple。")
        visible = {item.name: item for item in run.descriptors}

        def descriptor_for(name: str) -> ToolDescriptor | None:
            return visible.get(name) or self._descriptors.get(name)

        async def execute_one(call: ToolCall) -> ToolResult:
            return await self._execute_one(run, call, visible, approver)

        return await execute_ordered_batches(calls, descriptor_for, execute_one)

    def set_permission_mode(self, mode: PermissionMode) -> PermissionSnapshot:
        self._ensure_open()
        return self._permission.set_mode(mode)

    def set_shell_policy(self, policy: ShellPolicy) -> PermissionSnapshot:
        self._ensure_open()
        return self._permission.set_shell(policy)

    def state(self) -> PermissionSnapshot:
        self._ensure_open()
        return self._permission.snapshot()

    async def close(self) -> None:
        if self._mcp is not None:
            await self._mcp.close()
        self._closed = True

    async def _execute_one(
        self,
        run: ToolRun,
        call: ToolCall,
        visible: dict[str, ToolDescriptor],
        approver: Approver | None,
    ) -> ToolResult:
        descriptor = self._descriptors.get(call.name)
        if descriptor is None:
            return failure(call, "tool_not_found", f"未知工具：{call.name}")
        if call.name not in visible:
            return failure(call, "tool_not_allowed", f"当前 Run 不允许工具：{call.name}")
        if run.mode is RunMode.PLAN and descriptor.effect is not ToolEffect.OBSERVE:
            return failure(call, "tool_not_allowed", "Plan Run 只允许内置 observe Tool。")
        try:
            arguments = json.loads(call.arguments_json or "{}")
        except json.JSONDecodeError as exc:
            return failure(call, "invalid_arguments", f"工具参数不是合法 JSON：{exc}")
        if not isinstance(arguments, dict):
            return failure(call, "invalid_arguments", "工具参数 JSON 必须是对象。")
        prepared = (
            self._mcp.prepare(call, arguments, run)
            if descriptor.origin is ToolOrigin.MCP and self._mcp is not None
            else self._control.prepare(call, arguments, run)
            if descriptor.origin is ToolOrigin.SYSTEM and self._control is not None
            else self._builtin.prepare(call, arguments, run)
        )
        if isinstance(prepared, ToolResult):
            return prepared

        if prepared.command is not None:
            dangerous = self._dangerous.check(prepared.command, run.workspace.root)
            if dangerous is not None:
                return failure(call, "dangerous_command", dangerous)

        rule = explicit_rule(run, descriptor, prepared.target)
        if rule is not None:
            if not rule.allow:
                return failure(call, "permission_denied", "精确权限规则拒绝了本次调用。")
        else:
            action = mode_action(run, descriptor)
            if action == "ask":
                if run.source is ToolSource.SUBAGENT:
                    return failure(call, "permission_denied", "Subagent 不能发起交互审批。")
                if approver is None:
                    return failure(call, "permission_required", "本次调用需要人工审批。")
                try:
                    choice = await approver.approve(
                        ApprovalRequest(
                            descriptor.name,
                            prepared.target,
                            descriptor.effect,
                            run.workspace.root,
                            run.permission.mode,
                            run.permission.shell_policy,
                            run.source,
                        )
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    return failure(call, "permission_approval_error", str(exc))
                if not isinstance(choice, ApprovalChoice):
                    return failure(call, "permission_approval_error", "审批器返回非法选择。")
                if choice in {ApprovalChoice.ALLOW_ALWAYS, ApprovalChoice.DENY_ALWAYS}:
                    if not descriptor.rule_configurable:
                        return failure(call, "permission_rule_error", "该工具不允许持久规则。")
                    try:
                        self._permission.add_exact(
                            descriptor.name,
                            prepared.target,
                            allow=choice is ApprovalChoice.ALLOW_ALWAYS,
                        )
                    except Exception as exc:
                        return failure(call, "permission_rule_error", str(exc))
                if choice in {ApprovalChoice.DENY_ONCE, ApprovalChoice.DENY_ALWAYS}:
                    return failure(call, "permission_denied", "用户拒绝了本次调用。")
        try:
            return await asyncio.wait_for(
                prepared.execute(), timeout=self._tool_timeout_seconds
            )
        except TimeoutError:
            return failure(call, "tool_timeout", "工具执行超时。")

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("Tool 模块已关闭。")
