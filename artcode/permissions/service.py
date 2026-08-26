from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable
from typing import Protocol

from artcode.agent.events import AgentEvent, permission_audit_event

from artcode.tools.base import PreparedToolCall, ToolDescriptor, ToolEffect, ToolOrigin, ToolRunContext
from artcode.tools.results import ToolResult, denied_result, error_result

from .engine import PermissionEngine, is_persistent_rule_decision
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
        audit_sink: Callable[[AgentEvent], None] | None = None,
    ) -> None:
        self.state = state
        self.engine = engine
        self.approver = approver
        self.rule_writer = rule_writer
        self.audit_sink = audit_sink

    async def authorize(
        self,
        descriptor: ToolDescriptor,
        prepared: PreparedToolCall,
        context: ToolRunContext,
    ) -> ToolResult | None:
        if descriptor.origin is ToolOrigin.SYSTEM:
            # System tools do not access the workspace or change permission state.
            # Their own argument validation remains in the tool implementation.
            return None
        if descriptor.origin is ToolOrigin.MCP:
            return await self._authorize_mcp(descriptor, prepared, context)
        if self.engine is None:
            return None

        target = permission_target(descriptor, prepared)
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
            self._audit(
                "decision_failed",
                descriptor,
                target,
                ok=False,
                error_type=type(exc).__name__,
            )
            return error_result(descriptor.name, "permission_rule_error", str(exc))

        self._audit(
            "decision",
            descriptor,
            target,
            action=decision.action.value,
            source=decision.source.value,
            rule_index=decision.rule_index,
            rule_file_sha256=(
                _sha256(str(decision.rule_file)) if decision.rule_file is not None else None
            ),
            persistent_rule_hit=is_persistent_rule_decision(decision),
            ok=True,
        )

        if decision.action is PermissionAction.DENY:
            self._audit("denied", descriptor, target, source=decision.source.value, ok=True)
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
            self._audit("approval_unavailable", descriptor, prepared.preview.target, mcp=True, ok=False)
            return error_result(
                descriptor.name,
                "permission_required",
                "MCP 工具需要人工确认，但审批器不可用。",
            )
        try:
            self._audit("approval_requested", descriptor, prepared.preview.target, mcp=True, ok=True)
            allowed = await self.approver.request_mcp_approval(
                prepared.preview,
                context.mode.name == "plan",
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._audit(
                "approval_failed",
                descriptor,
                prepared.preview.target,
                mcp=True,
                ok=False,
                error_type=type(exc).__name__,
            )
            return error_result(descriptor.name, "permission_approval_error", str(exc))
        if not isinstance(allowed, bool):
            self._audit("approval_invalid", descriptor, prepared.preview.target, mcp=True, ok=False)
            return error_result(
                descriptor.name,
                "permission_approval_error",
                "MCP 审批器返回了非法结果。",
            )
        if not allowed:
            self._audit("denied", descriptor, prepared.preview.target, mcp=True, ok=True)
            return denied_result(descriptor.name)
        self._audit("approval_choice", descriptor, prepared.preview.target, mcp=True, choice="allow", ok=True)
        return None

    async def _resolve_approval(
        self,
        descriptor: ToolDescriptor,
        target: str,
        context: ToolRunContext,
        source: str,
    ) -> ToolResult | None:
        if self.approver is None:
            self._audit("approval_unavailable", descriptor, target, ok=False)
            return error_result(
                descriptor.name,
                "permission_required",
                "权限需要人工确认，但审批器不可用。",
            )
        try:
            self._audit("approval_requested", descriptor, target, ok=True)
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
            self._audit(
                "approval_failed",
                descriptor,
                target,
                ok=False,
                error_type=type(exc).__name__,
            )
            return error_result(descriptor.name, "permission_approval_error", str(exc))
        if not isinstance(choice, ApprovalChoice):
            self._audit("approval_invalid", descriptor, target, ok=False)
            return error_result(
                descriptor.name,
                "permission_approval_error",
                "审批器返回了非法选择。",
            )
        self._audit("approval_choice", descriptor, target, choice=choice.value, ok=True)

        if choice in {ApprovalChoice.ALLOW_ALWAYS, ApprovalChoice.DENY_ALWAYS}:
            if not descriptor.rule_configurable:
                self._audit("rule_write_failed", descriptor, target, ok=False, error_type="NotConfigurable")
                return error_result(
                    descriptor.name,
                    "permission_rule_error",
                    "该工具不允许写入永久权限规则。",
                )
            if self.rule_writer is None:
                self._audit("rule_write_failed", descriptor, target, ok=False, error_type="WriterUnavailable")
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
                self._audit(
                    "rule_write_failed",
                    descriptor,
                    target,
                    action=action.value,
                    ok=False,
                    error_type=type(exc).__name__,
                )
                return error_result(descriptor.name, "permission_rule_error", str(exc))
            self._audit("rule_written", descriptor, target, action=action.value, ok=True)

        if choice in {ApprovalChoice.DENY_ONCE, ApprovalChoice.DENY_ALWAYS}:
            self._audit("denied", descriptor, target, choice=choice.value, ok=True)
            return denied_result(descriptor.name)
        return None

    def _audit(
        self,
        event: str,
        descriptor: ToolDescriptor,
        target: str,
        **payload,
    ) -> None:
        if self.audit_sink is None:
            return
        try:
            self.audit_sink(
                permission_audit_event(
                    event,
                    tool_name=descriptor.name,
                    target_sha256=_sha256(target),
                    target_chars=len(target),
                    **payload,
                )
            )
        except Exception:
            # Instrumentation is optional and must not change permission behavior.
            return


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


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
