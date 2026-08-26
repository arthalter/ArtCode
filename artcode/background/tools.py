from __future__ import annotations

import json

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

from .manager import BackgroundTaskManager
from .presentation import handoff_payload


class _TaskTool(DescriptorBackedTool):
    def __init__(self, tasks: BackgroundTaskManager) -> None:
        self.tasks = tasks

    def prepare(self, arguments: dict, context: ToolRunContext):
        if context.is_subagent:
            return error_result(self.name, "task_control_forbidden", "子 Agent 不能控制后台任务。")
        return PreparedToolCall(self, arguments, ToolPreview(self.name, self.description, "任务管理器"))


class TaskListTool(_TaskTool):
    descriptor = ToolDescriptor(
        "task_list", "列出当前进程中的子 Agent 任务。",
        {"type": "object", "properties": {}, "additionalProperties": False},
        ToolEffect.READ, ToolOrigin.SYSTEM, False, False,
    )

    async def execute(self, prepared: PreparedToolCall, context: ToolRunContext):
        if prepared.arguments:
            return error_result(self.name, "invalid_arguments", "task_list 不接受参数。")
        return success_result(self.name, "已返回任务列表。", json.dumps([item.__dict__ | {"status": item.status.value} for item in self.tasks.list()], ensure_ascii=False, default=str))


class TaskGetTool(_TaskTool):
    descriptor = ToolDescriptor(
        "task_get", "查看一个子 Agent 的完整任务详情和成果交接信息。",
        {"type": "object", "properties": {"task_id": {"type": "string"}}, "required": ["task_id"], "additionalProperties": False},
        ToolEffect.READ, ToolOrigin.SYSTEM, False, False,
    )

    async def execute(self, prepared: PreparedToolCall, context: ToolRunContext):
        task_id = prepared.arguments.get("task_id")
        if not isinstance(task_id, str):
            return error_result(self.name, "invalid_arguments", "task_id 必须是字符串。")
        detail = self.tasks.get(task_id)
        if detail is None:
            return error_result(self.name, "task_not_found", "找不到任务。")
        return success_result(self.name, "已返回任务详情。", json.dumps(_detail(detail), ensure_ascii=False, default=str))


class TaskCancelTool(_TaskTool):
    descriptor = ToolDescriptor(
        "task_cancel", "取消尚未结束的子 Agent 任务；不会回滚其已产生的文件成果。",
        {"type": "object", "properties": {"task_id": {"type": "string"}}, "required": ["task_id"], "additionalProperties": False},
        ToolEffect.READ, ToolOrigin.SYSTEM, False, False,
    )

    async def execute(self, prepared: PreparedToolCall, context: ToolRunContext):
        task_id = prepared.arguments.get("task_id")
        if not isinstance(task_id, str):
            return error_result(self.name, "invalid_arguments", "task_id 必须是字符串。")
        if not self.tasks.cancel(task_id):
            return error_result(self.name, "task_not_cancellable", "任务不存在或已经结束。")
        return success_result(self.name, "已请求取消任务。", json.dumps({"task_id": task_id}, ensure_ascii=False))


def _detail(detail):
    result = detail.result
    return {
        "task_id": detail.task_id,
        "type": detail.kind,
        "role": detail.role_name,
        "status": detail.status.value,
        "background": detail.background,
        "result": None if result is None else result.final_text,
        "rounds": None if result is None else result.rounds,
        "usage": None if result is None else result.usage.to_dict(),
        "permission_events": None if result is None else [item.__dict__ for item in result.permission_events],
        "handoff": None if result is None else handoff_payload(result.handoff),
        "cache_prefix_preserved": (
            None if result is None else result.cache_prefix_preserved
        ),
        "stop_reason": None if result is None else result.stop_reason.value,
        "error": detail.error_message,
    }
