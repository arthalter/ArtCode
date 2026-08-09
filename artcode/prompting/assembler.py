from __future__ import annotations

from collections.abc import Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from artcode.tools import ToolEnvironment, ToolRunContext

if TYPE_CHECKING:
    from artcode.agent.modes import AgentMode

from .reminder import (
    SystemReminderBuilder,
    build_resume_reminder_message,
    collect_runtime_reminder_context,
)


@dataclass(frozen=True)
class PromptRequest:
    messages: tuple[dict[str, Any], ...]
    tools: tuple[dict[str, Any], ...] | None
    includes_resume_reminder: bool = False


class PromptRequestAssembler:
    def assemble(
        self,
        conversation_messages: Sequence[dict[str, Any]],
        mode: AgentMode | None,
        all_tools: Sequence[dict[str, Any]] | None,
        tool_context: ToolEnvironment | ToolRunContext,
        *,
        durable_system_prompt: str | None = None,
        include_resume_reminder: bool = False,
    ) -> PromptRequest:
        messages = deepcopy(conversation_messages)
        if durable_system_prompt is not None and messages and messages[0].get("role") == "system":
            messages[0]["content"] = durable_system_prompt
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
            messages.append(SystemReminderBuilder().build_message(reminder_context))
        if include_resume_reminder:
            messages.append(build_resume_reminder_message())
        return PromptRequest(
            messages=tuple(messages),
            tools=None if tools is None else tuple(tools),
            includes_resume_reminder=include_resume_reminder,
        )

    def _filtered_tools(
        self,
        mode: AgentMode | None,
        all_tools: Sequence[dict[str, Any]] | None,
    ) -> list[dict[str, Any]] | None:
        if all_tools is None:
            return None
        if mode is None:
            selected = list(all_tools)
        else:
            selected = mode.tool_policy.filter_openai_tools(list(all_tools))
        return [_without_internal_metadata(tool) for tool in selected]


def _tool_names(tools: Sequence[dict[str, Any]]) -> tuple[str, ...]:
    names: list[str] = []
    for tool in tools:
        function = tool.get("function")
        if isinstance(function, dict) and isinstance(function.get("name"), str):
            names.append(function["name"])
    return tuple(names)


def _without_internal_metadata(tool: dict[str, Any]) -> dict[str, Any]:
    clean = deepcopy(tool)
    for key in ("x-artcode-origin", "x-artcode-effect", "x-artcode-rule-configurable"):
        clean.pop(key, None)
    return clean
