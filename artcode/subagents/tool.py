from __future__ import annotations

import asyncio
import json

from artcode.background import BackgroundTaskManager
from artcode.background.presentation import handoff_payload
from artcode.conversation import ConversationContext
from artcode.tools import (
    DescriptorBackedTool,
    PreparedToolCall,
    ToolDescriptor,
    ToolEffect,
    ToolOrigin,
    ToolPreview,
    ToolRunContext,
    error_result,
    success_result,
)

from .factory import SubagentFactory
from .models import AgentCreateRequest, AgentKind
from .roles import RoleCatalog
from .runner import RunToCompletion


class AgentTool(DescriptorBackedTool):
    """The single stable model-facing entry point for all sub-agent creation."""

    descriptor = ToolDescriptor(
        name="agent",
        description="委派独立子任务。definition 使用预定义角色和干净上下文；fork 冻结当前对话快照并始终后台运行。",
        parameters_schema={
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": ["definition", "fork"]},
                "task": {"type": "string", "description": "可独立完成的明确子任务。"},
                "role": {"type": "string", "description": "definition 必填；fork 可选。"},
                "background": {"type": "boolean", "description": "definition 是否立即转后台。fork 固定后台。"},
            },
            "required": ["type", "task"],
            "additionalProperties": False,
        },
        effect=ToolEffect.READ,
        origin=ToolOrigin.SYSTEM,
        rule_configurable=False,
        subagent_allowed=False,
    )

    def __init__(
        self,
        catalog: RoleCatalog,
        factory: SubagentFactory,
        tasks: BackgroundTaskManager,
        parent_conversation: ConversationContext,
        *,
        foreground_timeout_seconds: float = 120.0,
        parent_request_provider=None,
        parent_policy_provider=None,
    ) -> None:
        self.catalog = catalog
        self.factory = factory
        self.tasks = tasks
        self.parent_conversation = parent_conversation
        self.foreground_timeout_seconds = foreground_timeout_seconds
        self.parent_request_provider = parent_request_provider
        self.parent_policy_provider = parent_policy_provider

    def prepare(self, arguments: dict, context: ToolRunContext):
        if context.is_subagent:
            return error_result(self.name, "nested_subagent_forbidden", "子 Agent 不能再次委派子 Agent。")
        try:
            unknown = set(arguments) - {"type", "task", "role", "background"}
            if unknown:
                raise ValueError(f"不支持的参数：{'、'.join(sorted(unknown))}")
            kind = AgentKind(arguments.get("type"))
            task = arguments.get("task")
            role = arguments.get("role")
            background = arguments.get("background") if "background" in arguments else None
            if role is not None and not isinstance(role, str):
                raise ValueError("role 必须是字符串。")
            if background is not None and not isinstance(background, bool):
                raise ValueError("background 必须是布尔值。")
            request = AgentCreateRequest(kind, task, role, background)
        except (TypeError, ValueError) as exc:
            return error_result(self.name, "invalid_arguments", str(exc))
        return PreparedToolCall(
            self,
            {"request": request},
            ToolPreview(self.name, f"委派 {request.kind.value} 子任务", request.task[:256]),
        )

    async def execute(self, prepared: PreparedToolCall, context: ToolRunContext):
        request: AgentCreateRequest = prepared.arguments["request"]
        snapshot = self.catalog.refresh(self.factory.tool_registry.descriptors())
        role = None if request.role_name is None else snapshot.get(request.role_name)
        if request.role_name is not None and role is None:
            related = [item for item in snapshot.diagnostics if item.role_name == request.role_name]
            message = related[0].message if related else f"找不到角色：{request.role_name}。"
            return error_result(self.name, "role_unavailable", message)
        parent_request = (
            self.parent_request_provider()
            if callable(self.parent_request_provider)
            else None
        )
        parent_messages = () if parent_request is None else parent_request.messages
        parent_tool_names = (
            frozenset()
            if parent_request is None
            else frozenset(
                function["name"]
                for tool in (parent_request.tools or ())
                if isinstance((function := tool.get("function")), dict)
                and isinstance(function.get("name"), str)
            )
        )
        parent_policy = (
            self.parent_policy_provider()
            if callable(self.parent_policy_provider)
            else None
        ) or context.mode.tool_policy
        launch = self.factory.prepare_launch(
            request,
            role=role,
            parent_snapshot=_forkable_snapshot(self.parent_conversation),
            parent_permission=context.permission,
            parent_policy=parent_policy,
            parent_messages=tuple(parent_messages) if request.kind is AgentKind.FORK else (),
            parent_tool_names=(
                parent_tool_names if request.kind is AgentKind.FORK and parent_request is not None else None
            ),
        )

        async def run(task_id: str):
            runtime = await self.factory.create(task_id, launch)
            return await RunToCompletion().run(runtime, self.factory.run_request(runtime))

        summary = self.tasks.submit(request, run, worktree_required=launch.capabilities.requires_worktree)
        if request.background:
            return success_result(self.name, "子 Agent 已在后台启动。", _summary_payload(summary))
        try:
            detail = await self.tasks.wait_foreground(
                summary.task_id, self.foreground_timeout_seconds
            )
        except asyncio.CancelledError:
            self.tasks.cancel(summary.task_id)
            await self.tasks.wait(summary.task_id)
            raise
        assert detail is not None
        if detail.status.value in {"queued", "running"}:
            manually_promoted = detail.background
            if not manually_promoted:
                self.tasks.promote_to_background(summary.task_id)
                detail = self.tasks.get(summary.task_id) or detail
            return success_result(
                self.name,
                (
                    "用户已将前台子 Agent 切换到后台继续运行。"
                    if manually_promoted
                    else "前台等待已超过 120 秒，子 Agent 将继续在后台运行。"
                ),
                _summary_payload(detail),
            )
        if detail.result is not None:
            status = detail.status.value
            if status in {"completed", "max_rounds"}:
                return success_result(self.name, "子 Agent 已完成。", _detail_payload(detail))
            if status == "cancelled":
                return error_result(
                    self.name, "subagent_cancelled", "子 Agent 已被取消。", _detail_payload(detail)
                )
            return error_result(
                self.name,
                "subagent_failed",
                detail.result.error_message or detail.error_message or "子 Agent 未能完成。",
                _detail_payload(detail),
            )
        return error_result(self.name, "subagent_failed", detail.error_message or "子 Agent 未能启动。")


def _summary_payload(summary) -> str:
    return json.dumps(
        {
            "task_id": summary.task_id,
            "type": summary.kind,
            "role": summary.role_name,
            "status": summary.status.value,
            "background": summary.background,
            "worktree_required": summary.worktree_required,
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _detail_payload(detail) -> str:
    result = detail.result
    return json.dumps(
        {
            "task_id": detail.task_id,
            "status": detail.status.value,
            "rounds": None if result is None else result.rounds,
            "stop_reason": None if result is None else result.stop_reason.value,
            "usage": None if result is None else result.usage.to_dict(),
            "result": None if result is None else result.final_text,
            "cache_prefix_preserved": (
                None if result is None else result.cache_prefix_preserved
            ),
            "handoff": None if result is None else handoff_payload(result.handoff),
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _forkable_snapshot(conversation: ConversationContext):
    """Exclude the parent turn's still-open delegation tool call.

    The parent has recorded the current `agent` call before its implementation
    runs. Copying that incomplete protocol pair would force the child to repair
    it as an interruption, so a Fork starts from the last completed boundary.
    """
    from artcode.conversation import ConversationSnapshot

    snapshot = conversation.snapshot()
    entries = snapshot.entries
    if entries and entries[-1].payload.get("role") == "assistant" and entries[-1].payload.get("tool_calls"):
        entries = entries[:-1]
    return ConversationSnapshot(snapshot.version, entries)
