from __future__ import annotations

import asyncio
from typing import Protocol

from artcode.tools.base import PreparedToolCall, ToolDescriptor, ToolEffect, ToolOrigin, ToolRunContext
from artcode.tools.results import ToolResult, denied_result, error_result

from .engine import PermissionEngine
from .models import (
    ApprovalChoice,
    ApprovalRequest,
    PermissionAction,
    PermissionRequest,
    PermissionState,
)
from .writer import RuleWriter


class ApprovalPort(Protocol):
    async def request_approval(self, request: ApprovalRequest) -> ApprovalChoice:
        ...

    async def request_mcp_approval(self, preview, plan_mode: bool) -> bool:
        ...


class PermissionService:
    def __init__(
        self,
        state: PermissionState,
        *,
        engine: PermissionEngine | None = None,
        approver: ApprovalPort | None = None,
        rule_writer: RuleWriter | None = None,
    ) -> None:
        self.state = state
        self.engine = engine
        self.approver = approver
        self.rule_writer = rule_writer

    async def authorize(
        self,
        descriptor: ToolDescriptor,
        prepared: PreparedToolCall,
        context: ToolRunContext,
    ) -> ToolResult | None:
        if descriptor.origin is ToolOrigin.MCP:
            return await self._authorize_mcp(descriptor, prepared, context)
        if self.engine is None:
            return None

        target = permission_target(descriptor, prepared)
        if descriptor.origin is ToolOrigin.SYSTEM:
            # System tools do not access the workspace or change permission state.
            # Their own argument validation remains in the tool implementation.
            return None
        try:
            decision = self.engine.decide(
                PermissionRequest(
                    tool_name=descriptor.name,
                    target=target,
                    workspace=context.default_cwd or context.path_policy.allowed_roots[0],
                    plan_mode=context.mode.name == "plan",
                    effect=descriptor.effect.value,
                    rule_configurable=descriptor.rule_configurable,
                ),
                context.permission,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return error_result(descriptor.name, "permission_rule_error", str(exc))

        if decision.action is PermissionAction.DENY:
            return error_result(
                descriptor.name,
                "permission_denied",
                decision.reason,
            )
        if decision.action is PermissionAction.ALLOW:
            return None
        return await self._resolve_approval(
            descriptor,
            target,
            context,
            decision.reason,
        )

    async def _authorize_mcp(
        self,
        descriptor: ToolDescriptor,
        prepared: PreparedToolCall,
        context: ToolRunContext,
    ) -> ToolResult | None:
        if self.approver is None:
            return error_result(
                descriptor.name,
                "permission_required",
                "MCP 工具需要人工确认，但审批器不可用。",
            )
        try:
            allowed = await self.approver.request_mcp_approval(
                prepared.preview,
                context.mode.name == "plan",
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return error_result(descriptor.name, "permission_approval_error", str(exc))
        if not isinstance(allowed, bool):
            return error_result(
                descriptor.name,
                "permission_approval_error",
                "MCP 审批器返回了非法结果。",
            )
        if not allowed:
            return denied_result(descriptor.name)
        return None

    async def _resolve_approval(
        self,
        descriptor: ToolDescriptor,
        target: str,
        context: ToolRunContext,
        source: str,
    ) -> ToolResult | None:
        if self.approver is None:
            return error_result(
                descriptor.name,
                "permission_required",
                "权限需要人工确认，但审批器不可用。",
            )
        try:
            choice = await self.approver.request_approval(
                ApprovalRequest(
                    tool_name=descriptor.name,
                    target=target,
                    workspace=context.default_cwd or context.path_policy.allowed_roots[0],
                    permission_mode=context.permission.mode,
                    shell_policy=context.permission.shell_policy,
                    source=source,
                )
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return error_result(descriptor.name, "permission_approval_error", str(exc))
        if not isinstance(choice, ApprovalChoice):
            return error_result(
                descriptor.name,
                "permission_approval_error",
                "审批器返回了非法选择。",
            )

        if choice in {ApprovalChoice.ALLOW_ALWAYS, ApprovalChoice.DENY_ALWAYS}:
            if not descriptor.rule_configurable:
                return error_result(
                    descriptor.name,
                    "permission_rule_error",
                    "该工具不允许写入永久权限规则。",
                )
            if self.rule_writer is None:
                return error_result(
                    descriptor.name,
                    "permission_rule_error",
                    "本地规则写入器不可用。",
                )
            action = (
                PermissionAction.ALLOW
                if choice is ApprovalChoice.ALLOW_ALWAYS
                else PermissionAction.DENY
            )
            try:
                self.rule_writer.write_exact(exact_match(descriptor.name, target), action)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                return error_result(descriptor.name, "permission_rule_error", str(exc))

        if choice in {ApprovalChoice.DENY_ONCE, ApprovalChoice.DENY_ALWAYS}:
            return denied_result(descriptor.name)
        return None


def permission_target(descriptor: ToolDescriptor, prepared: PreparedToolCall) -> str:
    if descriptor.effect is ToolEffect.SHELL:
        return str(prepared.arguments["command"]).strip()
    return prepared.preview.target


def exact_match(tool_name: str, target: str) -> str:
    escaped = (
        target.replace("\\", "\\\\")
        .replace("*", "\\*")
        .replace("?", "\\?")
        .replace("[", "\\[")
    )
    return f"{tool_name}({escaped})"
