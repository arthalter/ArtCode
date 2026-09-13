from __future__ import annotations

from pathlib import Path

from artcode._agent import AgentRunner
from artcode._session import LocalSession
from artcode._skill import LocalSkills
from artcode._tool import LocalTools
from artcode._workspace import LocalWorkspace
from artcode.core.agent import StopReason
from artcode.core.model import Completed, ModelRequest, TextDelta
from artcode.core.session import AssistantCompletion, AssistantFact, SessionSelection, UserFact
from artcode.core.skill import SkillMode
from artcode.core.tool import PermissionMode, RunMode
from tests.contracts.test_skill_interface import write_skill


class InspectingModel:
    def __init__(self, expected: str, reply: str) -> None:
        self.expected = expected
        self.reply = reply
        self.requests: list[ModelRequest] = []

    async def stream(self, request: ModelRequest):
        self.requests.append(request)
        assert self.expected in "\n".join(item.content or "" for item in request.prompt)
        yield TextDelta(self.reply)
        yield Completed("stop")

    async def close(self):
        return None


async def test_shared_skill_runs_in_main_session_with_frozen_contribution(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    write_skill(root / ".artcode/skills", "review", sop="SHARED-SOP")
    workspace = LocalWorkspace(root)
    tools = LocalTools(permission_mode=PermissionMode.FULL)
    session = LocalSession(root, SessionSelection.new())
    skills = LocalSkills(root / ".artcode/skills", tmp_path / "user", tmp_path / "builtin", known_tools=lambda: {item.name for item in tools.open_run(workspace, RunMode.CHAT).descriptors})
    skills.refresh()
    skills.activate("review")
    frozen = skills.freeze()
    run_tools = tools.open_run(workspace, RunMode.CHAT, allowed_tools=frozen.allowed_tools)
    lease = await session.prepare_run("review it", run_tools, contributions=frozen.contributions)
    model = InspectingModel("SHARED-SOP", "shared-result")

    events = [item async for item in AgentRunner(model, tools, session).run(session.dispatch_run(lease))]

    assert events[-1].outcome.stop_reason is StopReason.NATURAL
    assert session.snapshot().facts[-1] == AssistantFact("shared-result", AssistantCompletion.NATURAL)
    session.close()


async def test_isolated_skill_uses_temporary_transcript_and_returns_only_summary(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    write_skill(
        root / ".artcode/skills",
        "inspect",
        mode="isolated",
        history_turns=1,
        sop="ISOLATED-SOP",
    )
    workspace = LocalWorkspace(root)
    tools = LocalTools(permission_mode=PermissionMode.FULL)
    parent = LocalSession(root, SessionSelection.new())
    parent.commit_user("parent-history")
    parent.commit_assistant("parent-answer", AssistantCompletion.NATURAL)
    skills = LocalSkills(root / ".artcode/skills", tmp_path / "user", tmp_path / "builtin", known_tools=lambda: {"read_file"})
    skills.refresh()
    activation = skills.activate("inspect")
    model = InspectingModel("ISOLATED-SOP", "isolated-summary")

    result = await skills.run_isolated(
        activation.name,
        "inspect now",
        parent=parent,
        workspace=workspace,
        model=model,
        tools=tools,
    )

    assert result.stop_reason is StopReason.NATURAL
    assert result.summary == "isolated-summary"
    assert parent.snapshot().facts[-2:] == (
        UserFact("inspect now"),
        AssistantFact("isolated-summary", AssistantCompletion.NATURAL),
    )
    assert not any("ISOLATED-SOP" in getattr(item, "text", "") for item in parent.snapshot().facts)
    assert not (root / ".artcode/worktrees").exists()
    parent.close()
