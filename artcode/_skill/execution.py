from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from artcode._agent import AgentRunner
from artcode._session import LocalSession
from artcode.core.agent import RunFinished, StopReason
from artcode.core.model import Model, Usage
from artcode.core.session import (
    AssistantCompletion,
    AssistantFact,
    RunContribution,
    Session,
    SessionSelection,
    ToolExchangeFact,
    UserFact,
)
from artcode.core.skill import IsolatedSkillResult
from artcode.core.tool import RunMode, Tool, ToolSource
from artcode.core.workspace import Workspace

from .parsing import LoadedSkill


async def run_isolated(
    definition: LoadedSkill,
    user_content: str,
    *,
    parent: Session,
    workspace: Workspace,
    model: Model,
    tools: Tool,
    allowed_tools: frozenset[str],
) -> IsolatedSkillResult:
    if not isinstance(user_content, str) or not user_content.strip():
        raise ValueError("Isolated Skill 输入必须是非空字符串。")
    history = _recent_turns(
        parent.snapshot().facts,
        definition.candidate.metadata.history_turns,
    )
    parent.commit_user(user_content)
    with TemporaryDirectory(prefix="artcode-isolated-skill-") as raw:
        child = LocalSession(
            workspace.root,
            SessionSelection.new(),
            storage_root=Path(raw),
        )
        for fact in history:
            if isinstance(fact, UserFact):
                child.commit_user(fact.text)
            elif isinstance(fact, AssistantFact):
                child.commit_assistant(fact.text, fact.completion)
            elif isinstance(fact, ToolExchangeFact):
                child.commit_tool_exchange(
                    fact.requests,
                    fact.results,
                    metadata=fact.metadata,
                    assistant_text=fact.assistant_text,
                )
        run_tools = tools.open_run(
            workspace,
            RunMode.CHAT,
            source=ToolSource.ISOLATED_SKILL,
            allowed_tools=allowed_tools,
        )
        contribution = RunContribution(
            definition.name,
            definition.sop,
            definition.candidate.metadata.model,
        )
        lease = await child.prepare_run(
            user_content,
            run_tools,
            contributions=(contribution,),
        )
        events = tuple(
            [
                event
                async for event in AgentRunner(model, tools, child).run(
                    child.dispatch_run(lease)
                )
            ]
        )
        finished = next(event for event in reversed(events) if isinstance(event, RunFinished))
        outcome = finished.outcome
        if outcome.stop_reason in {StopReason.NATURAL, StopReason.LENGTH} and outcome.final_text:
            summary = outcome.final_text
            completion = (
                AssistantCompletion.LENGTH
                if outcome.stop_reason is StopReason.LENGTH
                else AssistantCompletion.NATURAL
            )
        else:
            summary = f"Skill {definition.name} 未能生成完成总结（{outcome.stop_reason.value}）。"
            completion = AssistantCompletion.NATURAL
        child.close()
    parent.commit_assistant(summary, completion)
    return IsolatedSkillResult(summary, outcome.stop_reason, outcome.usage, events)


def _recent_turns(facts: tuple, count: int) -> tuple:
    if count <= 0:
        return ()
    user_indexes = [index for index, fact in enumerate(facts) if isinstance(fact, UserFact)]
    if not user_indexes:
        return ()
    start = user_indexes[max(0, len(user_indexes) - count)]
    return facts[start:]
