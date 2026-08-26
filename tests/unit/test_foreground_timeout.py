from __future__ import annotations

import asyncio
import json
from pathlib import Path

from artcode.agent import NORMAL_AGENT_MODE
from artcode.background import BackgroundTaskManager
from artcode.conversation import ConversationContext
from artcode.permissions import PermissionState
from artcode.providers.events import content_delta_event, done_event
from artcode.subagents import RoleCatalog
from artcode.subagents.factory import SubagentFactory
from artcode.subagents.tool import AgentTool
from artcode.tools import ToolEnvironment, ToolRunContext
from tests.fixtures.providers import ScriptedProvider
from tests.fixtures.subagents import make_factory, write_role


class _GatedProvider:
    """Delays each stream until released, recording how many started."""

    def __init__(self) -> None:
        self.gate = asyncio.Event()
        self.started = 0
        self.requests: list[object] = []

    async def stream(self, request):
        self.requests.append(request)
        self.started += 1
        await self.gate.wait()
        yield content_delta_event("delayed result")
        yield done_event()

    async def close(self) -> None:
        return None


async def test_foreground_timeout_promotes_task_without_restarting_it(
    tmp_path: Path
) -> None:
    """E04: exceeding the foreground window stops waiting and returns the
    task id; the sub-agent itself is not interrupted or restarted."""
    role_dir = tmp_path / ".artcode" / "agents"
    write_role(role_dir / "reader.md", name="reader", allow=["read_file"])
    provider = _GatedProvider()
    tasks = BackgroundTaskManager()
    factory = make_factory(provider=provider, workspace=tmp_path)
    tool = AgentTool(
        RoleCatalog(project_dir=role_dir, user_dir=tmp_path / "u", builtin_dir=tmp_path / "b"),
        factory,
        tasks,
        ConversationContext(),
        foreground_timeout_seconds=0.05,
    )
    context = ToolRunContext(
        ToolEnvironment.from_workspace(tmp_path), NORMAL_AGENT_MODE, PermissionState().snapshot()
    )
    prepared = tool.prepare(
        {"type": "definition", "task": "慢任务", "role": "reader"}, context
    )

    result = await tool.execute(prepared, context)

    assert result.ok
    payload = json.loads(result.content)
    assert payload["status"] in {"queued", "running"}
    assert payload["background"] is True
    # The same task object keeps running after promotion: releasing the gate
    # completes it with the same identity and a single result.
    provider.gate.set()
    detail = await tasks.wait(payload["task_id"])
    assert detail is not None
    assert detail.status.value == "completed"
    assert detail.result is not None and detail.result.final_text == "delayed result"
    assert provider.started == 1
