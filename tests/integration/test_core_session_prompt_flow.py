from __future__ import annotations

from pathlib import Path

from artcode._session import LocalSession
from artcode._tool import LocalTools
from artcode._workspace import LocalWorkspace
from artcode.core.model import Completed, ModelRequest, TextDelta, Usage
from artcode.core.session import AssistantFact, RunCompletion, SessionSelection, UserFact
from artcode.core.tool import PermissionMode, RunMode


async def test_prepare_dispatch_finish_and_next_prompt_flow(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    workspace = LocalWorkspace(root)
    tools = LocalTools(permission_mode=PermissionMode.FULL)
    session = LocalSession(root, SessionSelection.new())
    session.add_notice("one-shot")

    first = await session.prepare_run("hello", tools.open_run(workspace, RunMode.CHAT))
    dispatched = session.dispatch_run(first)
    session.finish_run(first, RunCompletion.NATURAL, assistant_text="world", usage=Usage(4, 1, 5))
    second = await session.prepare_run("again", tools.open_run(workspace, RunMode.CHAT))

    assert "one-shot" in "\n".join(item.content or "" for item in dispatched.request.prompt)
    assert [type(item) for item in session.snapshot().facts] == [UserFact, AssistantFact, UserFact]
    assert [item.content for item in second.prompt_preview.prompt if item.role == "user"] == ["hello", "again"]
    assert any(item.role == "assistant" and item.content == "world" for item in second.prompt_preview.prompt)
    assert second.budget.source == "provider_usage"
    session.close()
