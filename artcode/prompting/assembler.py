from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from artcode.tools import ToolExecutionContext

if TYPE_CHECKING:
    from artcode.agent.modes import AgentMode

from .reminder import SystemReminderBuilder, collect_runtime_reminder_context


@dataclass(frozen=True)
class PromptRequest:
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] | None


class DurableSystemPromptSource(Protocol):
    def build_system_prompt(self) -> str:
        ...


class PromptRequestAssembler:
    def __init__(
        self,
        reminder_builder: SystemReminderBuilder | None = None,
        *,
        durable_prompt: DurableSystemPromptSource | None = None,
        resume_reminder_required: bool = False,
    ) -> None:
        self.reminder_builder = reminder_builder or SystemReminderBuilder()
        self.durable_prompt = durable_prompt
        self._resume_reminder_pending = resume_reminder_required

    def require_resume_reminder(self) -> None:
        self._resume_reminder_pending = True

    def assemble(
        self,
        conversation_messages: list[dict[str, Any]],
        mode: AgentMode | None,
        all_tools: list[dict[str, Any]] | None,
        tool_context: ToolExecutionContext,
    ) -> PromptRequest:
        messages = deepcopy(conversation_messages)
        if self.durable_prompt is not None and messages and messages[0].get("role") == "system":
            messages[0]["content"] = self.durable_prompt.build_system_prompt()
        tools = self._filtered_tools(mode, all_tools)
        if mode is not None:
            all_tool_names = _tool_names(all_tools or [])
            allowed_tool_names = _tool_names(tools or [])
            reminder_context = collect_runtime_reminder_context(
                mode,
                all_tool_names,
                allowed_tool_names,
                tool_context,
            )
            messages.append(self.reminder_builder.build_message(reminder_context))
            if self._resume_reminder_pending:
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "<system-reminder>\n"
                            "恢复会话距最后有效消息已超过 24 小时。文件、依赖、进程和运行环境可能已变化；"
                            "继续任务前应重新读取或验证相关现状，不要仅依据旧会话假设。\n"
                            "</system-reminder>"
                        ),
                    }
                )
                self._resume_reminder_pending = False
        return PromptRequest(messages=messages, tools=tools)

    def _filtered_tools(
        self,
        mode: AgentMode | None,
        all_tools: list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]] | None:
        if all_tools is None:
            return None
        if mode is None:
            selected = list(all_tools)
        else:
            selected = mode.tool_policy.filter_openai_tools(list(all_tools))
        return [_without_internal_metadata(tool) for tool in selected]


def _tool_names(tools: list[dict[str, Any]]) -> tuple[str, ...]:
    names: list[str] = []
    for tool in tools:
        function = tool.get("function")
        if isinstance(function, dict) and isinstance(function.get("name"), str):
            names.append(function["name"])
    return tuple(names)


def _without_internal_metadata(tool: dict[str, Any]) -> dict[str, Any]:
    clean = dict(tool)
    clean.pop("x-artcode-origin", None)
    return clean
