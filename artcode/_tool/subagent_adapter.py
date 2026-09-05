from __future__ import annotations

from dataclasses import replace
import json
from typing import Any

from artcode.core.model import ModelRequest
from artcode.core.subagent import ParentRunSnapshot, SubagentKind, TaskRequest
from artcode.core.tool import ToolCall, ToolDescriptor, ToolEffect, ToolOrigin, ToolResult, ToolRun

from .builtin import Prepared, _schema
from .results import failure, success


DESCRIPTORS = (
    ToolDescriptor(
        "agent",
        "创建定义式或 Fork 式 Subagent Task。",
        _schema(
            {
                "type": {"type": "string", "enum": ["definition", "fork"]},
                "task": {"type": "string"},
                "role": {"type": "string"},
                "background": {"type": "boolean"},
            },
            ["type", "task"],
        ),
        ToolEffect.CONTROL,
        ToolOrigin.SYSTEM,
        subagent_allowed=False,
        rule_configurable=False,
    ),
    ToolDescriptor(
        "task_list", "列出当前进程的 Subagent Tasks。",
        _schema({}, []), ToolEffect.CONTROL, ToolOrigin.SYSTEM,
        subagent_allowed=False, rule_configurable=False,
    ),
    ToolDescriptor(
        "task_get", "查看一个 Subagent Task。",
        _schema({"task_id": {"type": "string"}}, ["task_id"]),
        ToolEffect.CONTROL, ToolOrigin.SYSTEM, subagent_allowed=False, rule_configurable=False,
    ),
    ToolDescriptor(
        "task_cancel", "取消一个 Subagent Task。",
        _schema({"task_id": {"type": "string"}}, ["task_id"]),
        ToolEffect.CONTROL, ToolOrigin.SYSTEM, subagent_allowed=False, rule_configurable=False,
    ),
)


class SubagentToolAdapter:
    def __init__(self, subagents) -> None:
        self.subagents = subagents
        self.descriptors = DESCRIPTORS
        self._by_name = {item.name: item for item in DESCRIPTORS}

    def descriptor(self, name: str) -> ToolDescriptor | None:
        return self._by_name.get(name)

    def prepare(self, call: ToolCall, arguments: dict[str, Any], run: ToolRun) -> Prepared | ToolResult:
        descriptor = self.descriptor(call.name)
        if descriptor is None:
            return failure(call, "tool_not_found", f"未知 Task Tool：{call.name}")
        if call.name == "agent":
            allowed = {"type", "task", "role", "background"}
            if set(arguments) - allowed or not {"type", "task"} <= set(arguments):
                return failure(call, "invalid_arguments", "agent 参数字段无效。")
            try:
                kind = SubagentKind(arguments["type"])
                request = TaskRequest(
                    kind,
                    arguments["task"],
                    role=arguments.get("role"),
                    background=arguments.get("background", kind is SubagentKind.FORK),
                )
            except (TypeError, ValueError) as exc:
                return failure(call, "invalid_arguments", str(exc))
            if not isinstance(run.execution_data, ModelRequest):
                return failure(call, "parent_snapshot_missing", "agent 缺少冻结父 Prompt。")

            async def execute() -> ToolResult:
                parent = ParentRunSnapshot(run.execution_data, replace(run, execution_data=None))
                task = self.subagents.submit(request, parent)
                if kind is SubagentKind.DEFINITION and not task.background:
                    task = await self.subagents.wait_foreground(task.id)
                if task.state.value == "completed" and not task.background:
                    return success(call, _task_json(task))
                return success(call, json.dumps({"task_id": task.id, "state": task.state.value}, ensure_ascii=False))

            return Prepared(call, descriptor, request.task, execute)
        if call.name == "task_list":
            if arguments:
                return failure(call, "invalid_arguments", "task_list 不接受参数。")

            async def execute_list() -> ToolResult:
                return success(call, json.dumps([_task_payload(item) for item in self.subagents.list()], ensure_ascii=False))

            return Prepared(call, descriptor, "tasks", execute_list)
        if set(arguments) != {"task_id"} or not isinstance(arguments.get("task_id"), str):
            return failure(call, "invalid_arguments", f"{call.name} 只接受 task_id。")
        task_id = arguments["task_id"]

        async def execute_task_control() -> ToolResult:
            try:
                task = (
                    await self.subagents.cancel(task_id)
                    if call.name == "task_cancel"
                    else self.subagents.get(task_id)
                )
            except ValueError as exc:
                return failure(call, "task_not_found", str(exc))
            return success(call, _task_json(task))

        return Prepared(call, descriptor, task_id, execute_task_control)


def _task_payload(task) -> dict[str, object]:
    return {
        "id": task.id,
        "kind": task.kind.value,
        "role": task.role,
        "state": task.state.value,
        "background": task.background,
        "rounds": task.rounds,
        "result": task.result,
    }


def _task_json(task) -> str:
    return json.dumps(_task_payload(task), ensure_ascii=False)
