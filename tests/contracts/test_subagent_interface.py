from __future__ import annotations

import asyncio
from pathlib import Path

from artcode._session import LocalSession
from artcode._subagent import LocalSubagents
from artcode._tool import LocalTools
from artcode._workspace import LocalWorkspace
from artcode.core.model import Completed, ModelMessage, ModelRequest, TextDelta
from artcode.core.session import SessionSelection
from artcode.core.subagent import ParentRunSnapshot, SubagentKind, TaskRequest, TaskState
from artcode.core.tool import PermissionMode, RunMode


def write_role(
    root: Path,
    name: str,
    *,
    allow: tuple[str, ...] = ("read_file",),
    deny: tuple[str, ...] = (),
    model: str = "inherit",
    max_rounds: int = 10,
    permission_mode: str = "default",
    isolation: str = "none",
    sop: str = "ROLE-SOP",
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{name}.md"
    path.write_text(
        "---\n"
        f"name: {name}\n"
        f"description: {name} role\n"
        "tools:\n"
        f"  allow: {list(allow)!r}\n"
        f"  deny: {list(deny)!r}\n"
        f"model: {model}\n"
        f"max_rounds: {max_rounds}\n"
        f"permission_mode: {permission_mode}\n"
        f"isolation: {isolation}\n"
        "---\n"
        f"{sop}\n",
        encoding="utf-8",
    )
    return path


class RecordingModel:
    def __init__(self, reply: str = "done") -> None:
        self.reply = reply
        self.requests: list[ModelRequest] = []

    async def stream(self, request: ModelRequest):
        self.requests.append(request)
        yield TextDelta(self.reply)
        yield Completed("stop")

    async def close(self):
        return None


class Factory:
    def __init__(self) -> None:
        self.models: list[RecordingModel] = []

    def __call__(self, model: str | None):
        created = RecordingModel()
        self.models.append(created)
        return created


async def parent_snapshot(root: Path, workspace: LocalWorkspace, tools: LocalTools) -> ParentRunSnapshot:
    session = LocalSession(root, SessionSelection.new())
    run_tools = tools.open_run(workspace, RunMode.CHAT)
    lease = await session.prepare_run("PARENT-MARKER", run_tools)
    snapshot = ParentRunSnapshot(session.dispatch_run(lease).request, run_tools)
    session.close()
    return snapshot


async def test_definition_starts_clean_and_fork_keeps_exact_parent_prefix(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    write_role(root / ".artcode/agents", "reader", sop="READER-SOP")
    workspace = LocalWorkspace(root)
    tools = LocalTools(permission_mode=PermissionMode.FULL)
    factory = Factory()
    parent = await parent_snapshot(root, workspace, tools)
    subagents = LocalSubagents(
        root / ".artcode/agents", tmp_path / "user", tmp_path / "builtin",
        workspace=workspace, tools=tools, model_factory=factory,
    )
    subagents.refresh_roles()

    definition = subagents.submit(TaskRequest(SubagentKind.DEFINITION, "definition task", role="reader"), parent)
    fork = subagents.submit(TaskRequest(SubagentKind.FORK, "fork task", role="reader", background=True), parent)
    definition_done = await subagents.wait(definition.id)
    fork_done = await subagents.wait(fork.id)

    definition_prompt = factory.models[0].requests[0].prompt
    fork_prompt = factory.models[1].requests[0].prompt
    assert all("PARENT-MARKER" not in (item.content or "") for item in definition_prompt)
    assert any("READER-SOP" in (item.content or "") for item in definition_prompt)
    assert fork_prompt[: len(parent.prompt.prompt)] == parent.prompt.prompt
    assert fork_done.background is True
    assert definition_done.state is fork_done.state is TaskState.COMPLETED
    await subagents.close()


async def test_task_list_detail_and_notification_are_process_local_and_one_shot(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    write_role(root / ".artcode/agents", "reader")
    workspace = LocalWorkspace(root)
    tools = LocalTools(permission_mode=PermissionMode.FULL)
    parent = await parent_snapshot(root, workspace, tools)
    subagents = LocalSubagents(
        root / ".artcode/agents", tmp_path / "user", tmp_path / "builtin",
        workspace=workspace, tools=tools, model_factory=Factory(),
    )
    subagents.refresh_roles()

    task = subagents.submit(TaskRequest(SubagentKind.DEFINITION, "task", role="reader", background=True), parent)
    done = await subagents.wait(task.id)

    assert subagents.get(task.id) == done
    assert subagents.list() == (done,)
    notices = subagents.take_notifications()
    assert len(notices) == 1 and notices[0].task_id == task.id
    assert subagents.take_notifications() == ()
    assert notices[0].result == "done"
    await subagents.close()


async def test_invalid_role_and_invalid_request_fail_before_model_call(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    write_role(root / ".artcode/agents", "writer", allow=("write_file",), isolation="none")
    workspace = LocalWorkspace(root)
    tools = LocalTools()
    factory = Factory()
    parent = await parent_snapshot(root, workspace, tools)
    subagents = LocalSubagents(
        root / ".artcode/agents", tmp_path / "user", tmp_path / "builtin",
        workspace=workspace, tools=tools, model_factory=factory,
    )
    catalog = subagents.refresh_roles()

    assert all(item.name != "writer" for item in catalog.roles)
    failed = subagents.submit(TaskRequest(SubagentKind.DEFINITION, "task", role="writer"), parent)
    assert failed.state is TaskState.FAILED
    assert factory.models == []
    await subagents.close()


async def test_notification_truncates_at_8000_but_task_detail_keeps_full_result(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    write_role(root / ".artcode/agents", "reader")
    workspace = LocalWorkspace(root)
    tools = LocalTools()
    model = RecordingModel("x" * 8001)
    parent = await parent_snapshot(root, workspace, tools)
    subagents = LocalSubagents(
        root / ".artcode/agents", tmp_path / "user", tmp_path / "builtin",
        workspace=workspace, tools=tools, model_factory=lambda _: model,
    )
    subagents.refresh_roles()
    task = subagents.submit(TaskRequest(SubagentKind.DEFINITION, "long", role="reader", background=True), parent)
    detail = await subagents.wait(task.id)
    notice = subagents.take_notifications()[0]

    assert len(detail.result) == 8001
    assert len(notice.result) == 8000
    assert notice.truncated is True
    await subagents.close()
