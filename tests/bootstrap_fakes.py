from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path

from artcode.mcp import McpStartupReport
from artcode.permissions import ApprovalChoice
from artcode.providers.events import ContentDelta, StreamCompleted
from artcode.tui import UserRequestedExit


@dataclass
class BootstrapHarness:
    inputs: list[str] = field(default_factory=lambda: ["/exit"])
    events: list[str] = field(default_factory=list)
    startups: list[object] = field(default_factory=list)
    mcp_reports: list[McpStartupReport] = field(default_factory=list)
    runtime_statuses: list[object] = field(default_factory=list)
    provider_requests: list[object] = field(default_factory=list)
    response_text: str = "测试回复"
    failure_stage: str | None = None
    close_failure: str | None = None


def write_config(home: Path, *, model: str = "deepseek-v4-flash") -> Path:
    home.mkdir(parents=True, exist_ok=True)
    path = home / "config.yml"
    path.write_text(
        "\n".join(
            (
                "protocol: openai",
                f"model: {model}",
                "base_url: https://example.invalid",
                "api_key: sk-bootstrap-test",
                "thinking:",
                "  enabled: false",
                "context:",
                "  window_tokens: 200000",
                "",
            )
        ),
        encoding="utf-8",
    )
    return path


def install_bootstrap_fakes(monkeypatch, harness: BootstrapHarness) -> None:
    import artcode.bootstrap as module

    RealSessionService = module.SessionService
    RealArtifactStore = module.ContextArtifactStore
    RealMemoryService = module.MemoryService
    RealPromptSource = module.DurablePromptSource

    class FakeProvider:
        def __init__(self, config) -> None:
            harness.events.append("provider:create")
            if harness.failure_stage == "provider":
                raise RuntimeError("provider start failure")

        async def stream(self, request):
            harness.provider_requests.append(request)
            yield ContentDelta(harness.response_text)
            yield StreamCompleted()

        async def close(self) -> None:
            harness.events.append("provider:close")
            if harness.close_failure == "provider":
                raise RuntimeError("provider close failure")

    class FakeSeatbelt:
        def __init__(self, workspace, sensitive_paths) -> None:
            self.workspace = workspace
            self.sensitive_paths = sensitive_paths
            self.self_tested = False
            harness.events.append("seatbelt:create")

        async def start(self):
            if harness.failure_stage == "seatbelt":
                raise RuntimeError("seatbelt start failure")
            self.self_tested = True
            harness.events.append("seatbelt:start")
            return self

        def close(self) -> None:
            self.self_tested = False
            harness.events.append("seatbelt:close")
            if harness.close_failure == "seatbelt":
                raise RuntimeError("seatbelt close failure")

    class FakeMcpManager:
        def __init__(self, configs, workspace, issues=(), approver=None) -> None:
            self.report = McpStartupReport(configured_count=len(configs) + len(issues))
            harness.events.append("mcp:create")

        async def start(self):
            if harness.failure_stage == "mcp":
                raise RuntimeError("mcp start failure")
            harness.events.append("mcp:start")
            return self.report

        def register_into(self, registry):
            harness.events.append("mcp:register")
            return ()

        async def close(self) -> None:
            harness.events.append("mcp:close")
            if harness.close_failure == "mcp":
                raise RuntimeError("mcp close failure")

    class FakeTui:
        def __init__(self, renderer) -> None:
            self.renderer = renderer

        def show_startup(self, status) -> None:
            harness.startups.append(status)

        def show_mcp_startup(self, report) -> None:
            harness.mcp_reports.append(report)

        async def read_input(self, model: str) -> str:
            if not harness.inputs:
                raise UserRequestedExit
            value = harness.inputs.pop(0)
            if value == "__cancel__":
                raise asyncio.CancelledError
            return value

        def show_help(self, message: str) -> None:
            harness.events.append(f"help:{message}")

        def show_error(self, error) -> None:
            harness.events.append(f"error:{error}")

        def show_cancelled(self) -> None:
            harness.events.append("runtime:cancelled")

        def show_exit(self) -> None:
            harness.events.append("runtime:exit")

        def show_user_label(self) -> None:
            harness.events.append("runtime:user")

        def show_assistant_label(self) -> None:
            harness.events.append("runtime:assistant")

        def stream_delta(self, text: str) -> None:
            harness.events.append(f"delta:{text}")

        def finish_assistant_message(self) -> None:
            harness.events.append("runtime:message-finished")

        async def confirm_unsandboxed(self) -> bool:
            return False

        async def request_approval(self, request):
            return ApprovalChoice.ALLOW_ONCE

        async def confirm_mcp_tool(self, preview, plan_mode: bool) -> bool:
            return True

        async def confirm_mcp_server(self, config) -> bool:
            return True

        def show_tool_result_summary(self, result) -> None:
            harness.events.append(f"tool:{result.status}")

        def show_agent_iteration(self, current, maximum) -> None:
            harness.events.append(f"iteration:{current}")

        def show_tool_calls_received(self, count) -> None:
            harness.events.append(f"tool-calls:{count}")

        def show_tool_batch_started(self, batch_index, safety, count) -> None:
            harness.events.append(f"batch:{batch_index}")

        def show_token_usage(self, *args) -> None:
            harness.events.append("runtime:usage")

        def show_agent_stopped(self, reason, message="") -> None:
            harness.events.append(f"stopped:{reason}")

        def show_context_status(self, payload) -> None:
            harness.events.append(f"context:{payload['status']}")

        def show_persistence_status(self, payload) -> None:
            harness.events.append(f"persistence:{payload['status']}")

        def set_display_mode(self, mode) -> None:
            harness.events.append(f"mode:{mode.value}")

        def clear_screen(self) -> None:
            harness.events.append("runtime:clear")

        def show_runtime_status(self, snapshot) -> None:
            harness.runtime_statuses.append(snapshot)

    class RecordingSessionService(RealSessionService):
        def __init__(self, paths) -> None:
            super().__init__(paths)
            harness.events.append("session:create")

        def start(self, selection=None, now=None):
            if harness.failure_stage == "session":
                raise RuntimeError("session start failure")
            harness.events.append("session:start")
            return super().start(selection, now)

        def close(self) -> None:
            harness.events.append("session:close")
            super().close()
            if harness.close_failure == "session":
                raise RuntimeError("session close failure")

    class RecordingArtifactStore(RealArtifactStore):
        def __init__(self, workspace, session_id=None) -> None:
            super().__init__(workspace, session_id)
            harness.events.append("artifact:create")

        def start(self) -> None:
            if harness.failure_stage == "artifact":
                raise RuntimeError("artifact start failure")
            harness.events.append("artifact:start")
            super().start()

        def close(self) -> None:
            harness.events.append("artifact:close")
            super().close()
            if harness.close_failure == "artifact":
                raise RuntimeError("artifact close failure")

    class RecordingMemoryService(RealMemoryService):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            harness.events.append("memory:create")

        async def close(self) -> None:
            harness.events.append("memory:close")
            await super().close()
            if harness.close_failure == "memory":
                raise RuntimeError("memory close failure")

    class RecordingPromptSource(RealPromptSource):
        def __init__(self, *args, **kwargs) -> None:
            if harness.failure_stage == "prompt":
                raise RuntimeError("prompt start failure")
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(module, "DeepSeekChatProvider", FakeProvider)
    monkeypatch.setattr(module, "SessionService", RecordingSessionService)
    monkeypatch.setattr(module, "ContextArtifactStore", RecordingArtifactStore)
    monkeypatch.setattr(module, "SeatbeltSession", FakeSeatbelt)
    monkeypatch.setattr(module, "McpManager", FakeMcpManager)
    monkeypatch.setattr(module, "MemoryService", RecordingMemoryService)
    monkeypatch.setattr(module, "DurablePromptSource", RecordingPromptSource)
    monkeypatch.setattr(module, "PromptToolkitTui", FakeTui)


__all__ = ["BootstrapHarness", "install_bootstrap_fakes", "write_config"]
