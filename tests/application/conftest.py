from __future__ import annotations

from pathlib import Path

from artcode.core.application import ApplicationOptions
from artcode.core.model import Completed, ModelMessage, ModelRequest, TextDelta, Usage
from artcode.core.session import SessionSelection


def write_config(path: Path, **overrides) -> Path:
    values = {
        "protocol": "openai",
        "model": "test-model",
        "base_url": "https://example.invalid/v1",
        "api_key": "test-secret",
    }
    values.update(overrides)
    path.parent.mkdir(parents=True, exist_ok=True)
    import yaml

    path.write_text(yaml.safe_dump(values, sort_keys=False), encoding="utf-8")
    return path


def options(tmp_path: Path) -> ApplicationOptions:
    workspace = tmp_path / "workspace"
    home = tmp_path / "home"
    workspace.mkdir()
    home.mkdir()
    config = write_config(home / "config.yml")
    return ApplicationOptions(workspace, config, home, SessionSelection.new())


class FakeModel:
    def __init__(self) -> None:
        self.requests: list[ModelRequest] = []
        self.closed = 0

    async def stream(self, request: ModelRequest):
        self.requests.append(request)
        system = "\n".join(item.content or "" for item in request.prompt if item.role == "system")
        if "Extract durable memory" in system:
            yield TextDelta('{"user_preferences":[],"project_facts":[]}')
            yield Completed("stop")
            return
        if "Summarize only" in system:
            yield TextDelta("summary")
            yield Completed("stop")
            return
        user = next((item.content for item in reversed(request.prompt) if item.role == "user"), "")
        if user and user.startswith("执行以下计划"):
            reply = "ACTED"
        elif user == "make a plan":
            reply = "THE PLAN"
        else:
            reply = f"reply:{user}"
        yield TextDelta(reply)
        yield Usage(4, 2, 6)
        yield Completed("stop")

    async def close(self):
        self.closed += 1


class AllowInteraction:
    async def approve(self, request):
        from artcode.core.tool import ApprovalChoice

        return ApprovalChoice.ALLOW_ONCE

    async def approve_mcp_server(self, name: str, summary: str) -> bool:
        return True

    async def confirm_worktree_discard(self, handoff) -> bool:
        return True

    async def choose_active_task_exit(self, tasks) -> str:
        return "cancel"
