from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from copy import deepcopy

from artcode.agent import AgentLoop, AgentRunRequest, NORMAL_AGENT_MODE, PlanMemory, RequestPreparer
from artcode.agent.events import AgentEvent, AgentEventType, StopReason
from artcode.conversation import ConversationContext, ConversationPersistenceRejected

from .models import SkillDefinition


class SkillExecutionCoordinator:
    """Runs slash-invoked Skills without giving them any extra execution power."""

    def __init__(self, main_loop: AgentLoop) -> None:
        self.main_loop = main_loop

    async def run(
        self,
        definition: SkillDefinition,
        user_content: str,
    ) -> AsyncIterator[AgentEvent]:
        if definition.metadata.mode.value == "shared":
            request = AgentRunRequest(
                user_content=user_content,
                mode=NORMAL_AGENT_MODE,
                model_override=definition.metadata.model,
            )
            async for event in self.main_loop.run(request):
                yield event
            return
        async for event in self._run_isolated(definition, user_content):
            yield event

    async def _run_isolated(
        self,
        definition: SkillDefinition,
        user_content: str,
    ) -> AsyncIterator[AgentEvent]:
        parent = self.main_loop.conversation
        history = _recent_complete_turns(
            parent.export_messages(), definition.metadata.history_turns
        )
        try:
            parent.append_user(user_content, mode=f"skill:{definition.name}")
        except ConversationPersistenceRejected as exc:
            from artcode.agent.events import run_started_event, stopped_event

            yield run_started_event(NORMAL_AGENT_MODE.name, None)
            yield stopped_event(StopReason.STREAM_ERROR, str(exc))
            return

        child = _child_conversation(history)
        parent_preparer = self.main_loop.request_preparer
        child_preparer = RequestPreparer(
            child,
            parent_preparer.assembler,
            self.main_loop.tool_registry,
            self.main_loop.tool_environment,
            parent_preparer.permission_state,
            durable_prompt=parent_preparer.durable_prompt,
            skill_service=parent_preparer.skill_service,
        )
        child_loop = AgentLoop(
            provider=self.main_loop.provider,
            conversation=child,
            tool_registry=self.main_loop.tool_registry,
            tool_environment=self.main_loop.tool_environment,
            plan_memory=PlanMemory(),
            tool_executor=self.main_loop.tool_executor,
            request_preparer=child_preparer,
        )
        stopped: StopReason | None = None
        request = AgentRunRequest(
            user_content=user_content,
            mode=NORMAL_AGENT_MODE,
            model_override=definition.metadata.model,
        )
        async for event in child_loop.run(request):
            if event.type is AgentEventType.STOPPED:
                try:
                    stopped = StopReason(event.payload["reason"])
                except (KeyError, TypeError, ValueError):
                    stopped = StopReason.STREAM_ERROR
            yield event

        summary = _last_assistant_text(child)
        if not summary:
            summary = _failure_summary(definition.name, stopped)
        try:
            parent.append_assistant(summary, mode=f"skill:{definition.name}")
        except ConversationPersistenceRejected:
            # The child has already completed; do not let a journal failure corrupt
            # its isolated result or the parent conversation in memory.
            return


def _recent_complete_turns(
    messages: Sequence[dict],
    count: int,
) -> list[dict]:
    if count == 0:
        return []
    user_indexes = [
        index for index, message in enumerate(messages) if message.get("role") == "user"
    ]
    if not user_indexes:
        return []
    start = user_indexes[max(0, len(user_indexes) - count)]
    # Starting at a user message keeps every following assistant tool-call and
    # tool-result pair intact instead of slicing through a protocol unit.
    selected = list(messages[start:])
    if messages and messages[0].get("role") == "system":
        selected.insert(0, messages[0])
    return deepcopy(selected)


def _child_conversation(history: Sequence[dict]) -> ConversationContext:
    system = ""
    if history and history[0].get("role") == "system":
        system = str(history[0].get("content", ""))
    child = ConversationContext(system_prompt=system)
    if not history:
        return child
    entries = [child.make_entry(dict(message)) for message in history]
    child.replace_entries_if_version(child.version, entries)
    return child


def _last_assistant_text(conversation: ConversationContext) -> str:
    for message in reversed(conversation.export_messages()):
        if message.get("role") == "assistant" and isinstance(message.get("content"), str):
            if message["content"]:
                return message["content"]
    return ""


def _failure_summary(name: str, reason: StopReason | None) -> str:
    if reason is StopReason.USER_CANCELLED:
        return f"Skill {name} 的独立子对话已取消，未产生完成总结。"
    return f"Skill {name} 的独立子对话未能生成完成总结。"
