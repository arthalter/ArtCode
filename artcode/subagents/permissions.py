from __future__ import annotations

import time
import hashlib

from artcode.permissions import PermissionMode, PermissionSnapshot, PermissionState, ShellPolicy
from artcode.permissions.service import PermissionService
from artcode.tools.results import ToolResult, error_result

from .models import PermissionEvent, RoleDefinition


_MODE_RANK = {
    PermissionMode.DEFAULT: 0,
    PermissionMode.EDIT: 1,
    PermissionMode.FULL: 2,
}


def restrict_permission(parent: PermissionSnapshot, role: RoleDefinition | None) -> PermissionState:
    role_mode = PermissionMode.DEFAULT if role is None else role.permission_mode
    mode = parent.mode if _MODE_RANK[parent.mode] <= _MODE_RANK[role_mode] else role_mode
    # A child never inherits the parent's one-off switch to an unsandboxed
    # shell. This is a strict reduction and keeps the Worktree boundary backed
    # by the OS sandbox as well as the tool path policy.
    return PermissionState(mode=mode, shell_policy=ShellPolicy.SANDBOX_AUTO)


class SubagentPermissionService(PermissionService):
    """Permission port that records but never opens an interactive approval UI."""

    def __init__(self, task_id: str, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.task_id = task_id
        self.events: list[PermissionEvent] = []

    async def _authorize_mcp(self, descriptor, prepared, context) -> ToolResult | None:
        self._record(descriptor.name, "auto_denied", "subagent", prepared.preview.target)
        return error_result(
            descriptor.name,
            "approval_required_in_subagent",
            "子 Agent 不能请求 MCP 或其他需要人工确认的操作。",
        )

    async def _resolve_approval(self, descriptor, target, context, source) -> ToolResult | None:
        self._record(descriptor.name, "auto_denied", source, target)
        return error_result(
            descriptor.name,
            "approval_required_in_subagent",
            "该操作需要人工确认；子 Agent 以非交互方式运行，已自动拒绝。",
        )

    def record_runtime_denial(self, tool_name: str, source: str) -> None:
        self._record(tool_name, "denied", source, "")

    def _audit(self, event: str, descriptor, target: str, **payload) -> None:
        super()._audit(event, descriptor, target, **payload)
        if event == "decision":
            action = str(payload.get("action", "unknown"))
            if action != "ask":
                self._record(
                    descriptor.name,
                    "allowed" if action == "allow" else "denied",
                    str(payload.get("source", "permission_engine")),
                    target,
                )
        elif event == "decision_failed":
            self._record(descriptor.name, "error", "permission_engine", target)

    def _record(self, tool_name: str, decision: str, source: str, target: str) -> None:
        digest = hashlib.sha256(target.encode("utf-8", errors="replace")).hexdigest()
        self.events.append(
            PermissionEvent(
                task_id=self.task_id,
                tool_name=tool_name,
                decision=decision,
                source=source,
                target_summary=f"sha256:{digest}; chars:{len(target)}",
                timestamp=time.time(),
            )
        )
