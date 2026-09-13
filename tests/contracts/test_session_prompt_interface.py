from __future__ import annotations

from pathlib import Path

from artcode._session import LocalSession
from artcode._tool import LocalTools
from artcode._workspace import LocalWorkspace
from artcode.core.session import (
    RunCompletion,
    RunContribution,
    SessionSelection,
)
from artcode.core.tool import PermissionMode, RunMode


def content(request) -> str:
    return "\n".join(message.content or "" for message in request.prompt)


async def test_prompt_projects_sources_with_explicit_boundaries_and_frozen_tools(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    user_home = tmp_path / "home"
    (root / ".artcode").mkdir(parents=True)
    user_home.mkdir()
    (root / "ARTCODE.md").write_text("project-root-rule", encoding="utf-8")
    (root / ".artcode/instructions.md").write_text("project-local-rule", encoding="utf-8")
    (user_home / "instructions.md").write_text("user-rule", encoding="utf-8")
    workspace = LocalWorkspace(root)
    tools = LocalTools(permission_mode=PermissionMode.FULL)
    tool_run = tools.open_run(workspace, RunMode.CHAT)
    session = LocalSession(root, SessionSelection.new(), user_home=user_home)
    session.commit_user("earlier-user")
    session.commit_assistant("earlier-assistant", __import__("artcode.core.session", fromlist=["AssistantCompletion"]).AssistantCompletion.NATURAL)

    lease = await session.prepare_run(
        "current-goal",
        tool_run,
        contributions=(RunContribution("review", "skill-rule", model="special-model"),),
    )

    rendered = content(lease.prompt_preview)
    assert '<instructions source="project-local">' in rendered
    assert '<instructions source="project-root">' in rendered
    assert '<instructions source="user">' in rendered
    assert '<skill name="review">' in rendered
    assert rendered.index("project-local-rule") < rendered.index("project-root-rule") < rendered.index("user-rule")
    assert [message.content for message in lease.prompt_preview.prompt if message.role == "user"] == ["earlier-user", "current-goal"]
    assert lease.prompt_preview.model == "special-model"
    assert {item.name for item in lease.tools.descriptors} == {item.name for item in tool_run.descriptors}
    assert {item.name for item in lease.prompt_preview.tools} == {item.name for item in tool_run.descriptors}
    session.close()


async def test_notice_is_not_consumed_by_snapshot_preview_or_failed_preparation(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    workspace = LocalWorkspace(root)
    tools = LocalTools()
    session = LocalSession(root, SessionSelection.new())
    session.add_notice("recheck environment")

    lease = await session.prepare_run("goal", tools.open_run(workspace, RunMode.CHAT))

    assert "recheck environment" not in content(lease.prompt_preview)
    assert session.snapshot().pending_notices == ("recheck environment",)
    dispatched = session.dispatch_run(lease)
    assert '<notice id="' in content(dispatched.request)
    assert "recheck environment" in content(dispatched.request)
    assert session.snapshot().pending_notices == ()
    assert session.dispatch_run(lease).request == dispatched.request

    next_lease = await session.prepare_run("next", tools.open_run(workspace, RunMode.CHAT))
    assert "recheck environment" not in content(session.dispatch_run(next_lease).request)
    session.close()


async def test_run_lease_is_immutable_after_later_transcript_changes(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    workspace = LocalWorkspace(root)
    tools = LocalTools()
    session = LocalSession(root, SessionSelection.new())
    lease = await session.prepare_run("first", tools.open_run(workspace, RunMode.CHAT))
    frozen = lease.prompt_preview
    session.commit_user("later")

    assert lease.prompt_preview == frozen
    assert "later" not in content(frozen)
    session.close()


async def test_successful_plan_usage_and_resume_notice_are_persisted(tmp_path: Path) -> None:
    from artcode.core.model import Usage

    root = tmp_path / "workspace"
    root.mkdir()
    workspace = LocalWorkspace(root)
    tools = LocalTools()
    created = LocalSession(root, SessionSelection.new(), clock=lambda: 1.0)
    lease = await created.prepare_run("make plan", tools.open_run(workspace, RunMode.PLAN))
    created.dispatch_run(lease)
    created.finish_run(
        lease,
        RunCompletion.NATURAL,
        assistant_text="the-plan",
        usage=Usage(20, 5, 25),
    )
    identifier = created.snapshot().session_id
    created.close()

    restored = LocalSession(root, SessionSelection.exact(identifier), clock=lambda: 100_000.0)
    snapshot = restored.snapshot()
    assert snapshot.latest_plan == "the-plan"
    assert snapshot.last_usage == Usage(20, 5, 25)
    assert any("环境" in item for item in snapshot.pending_notices)
    restored.close()
