from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from artcode.agent.modes import AgentMode
from artcode.tools import ToolExecutionContext

from .reminder import SystemReminderBuilder, collect_runtime_reminder_context


@dataclass(frozen=True)
class PromptRequest:
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] | None


class PromptRequestAssembler:
    def __init__(self, reminder_builder: SystemReminderBuilder | None = None) -> None:
        self.reminder_builder = reminder_builder or SystemReminderBuilder()

    def assemble(
        self,
        conversation_messages: list[dict[str, Any]],
        mode: AgentMode | None,
        all_tools: list[dict[str, Any]] | None,
        tool_context: ToolExecutionContext,
    ) -> PromptRequest:
        messages = deepcopy(conversation_messages)
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
        return PromptRequest(messages=messages, tools=tools)

    def _filtered_tools(
        self,
        mode: AgentMode | None,
        all_tools: list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]] | None:
        if all_tools is None:
            return None
        if mode is None:
            return list(all_tools)
        return mode.tool_policy.filter_openai_tools(list(all_tools))


def _tool_names(tools: list[dict[str, Any]]) -> tuple[str, ...]:
    names: list[str] = []
    for tool in tools:
        function = tool.get("function")
        if isinstance(function, dict) and isinstance(function.get("name"), str):
            names.append(function["name"])
    return tuple(names)
