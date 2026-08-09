from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from artcode.commands.base import DisplayMode
from artcode.permissions import PermissionMode, PermissionSnapshot, PermissionState, ShellPolicy

if TYPE_CHECKING:
    from artcode.agent.events import TokenUsage
    from artcode.config import ArtCodeConfig


@dataclass(frozen=True)
class StartupStatusSnapshot:
    protocol: str
    model: str
    base_url: str
    streaming: bool
    thinking_enabled: bool
    api_key_configured: bool
    workspace: str = ""
    permission_mode: str = "default"
    shell_policy: str = "auto"
    seatbelt_status: str = "not initialized"
    context_window_tokens: int = 1_000_000
    session_id: str = ""
    session_state: str = "disabled"
    recovered_messages: int = 0
    bad_session_lines: int = 0
    session_truncated: bool = False
    instruction_bytes: int = 0
    instruction_issues: int = 0
    user_active_notes: int = 0
    project_active_notes: int = 0

    @classmethod
    def from_config(cls, config: ArtCodeConfig) -> "StartupStatusSnapshot":
        return cls(
            protocol=config.protocol,
            model=config.model,
            base_url=config.base_url,
            streaming=True,
            thinking_enabled=config.thinking.enabled,
            api_key_configured=bool(config.api_key),
            context_window_tokens=config.context.window_tokens,
        )


@dataclass(frozen=True)
class RuntimeStatusSnapshot:
    model: str
    workspace: str
    display_mode: DisplayMode
    permission_mode: str
    shell_policy: str
    seatbelt_status: str
    session_id: str | None
    session_state: str
    estimated_context_tokens: int | None
    context_window_tokens: int
    last_token_usage: TokenUsage | None = None


@dataclass
class RuntimeState:
    permission: PermissionState
    display_mode: DisplayMode = DisplayMode.DEFAULT
    last_token_usage: TokenUsage | None = None

    @property
    def permission_snapshot(self) -> PermissionSnapshot:
        return self.permission.snapshot()

    def set_permission_mode(self, mode: PermissionMode) -> None:
        self.permission.mode = mode

    def set_shell_policy(self, policy: ShellPolicy) -> None:
        self.permission.shell_policy = policy

    def set_display_mode(self, mode: DisplayMode) -> None:
        self.display_mode = mode

    def record_usage(self, usage: TokenUsage) -> None:
        self.last_token_usage = usage

    def startup_snapshot(
        self,
        config: ArtCodeConfig,
        *,
        workspace: str = "",
        seatbelt_status: str = "not initialized",
    ) -> StartupStatusSnapshot:
        permission = self.permission_snapshot
        return replace(
            StartupStatusSnapshot.from_config(config),
            workspace=workspace,
            permission_mode=permission.mode.value,
            shell_policy=permission.shell_policy.value,
            seatbelt_status=seatbelt_status,
        )

    def status_snapshot(
        self,
        *,
        model: str,
        workspace: str,
        seatbelt_status: str,
        session_id: str | None,
        session_state: str,
        estimated_context_tokens: int | None,
        context_window_tokens: int,
    ) -> RuntimeStatusSnapshot:
        permission = self.permission_snapshot
        return RuntimeStatusSnapshot(
            model=model,
            workspace=workspace,
            display_mode=self.display_mode,
            permission_mode=permission.mode.value,
            shell_policy=permission.shell_policy.value,
            seatbelt_status=seatbelt_status,
            session_id=session_id,
            session_state=session_state,
            estimated_context_tokens=estimated_context_tokens,
            context_window_tokens=context_window_tokens,
            last_token_usage=self.last_token_usage,
        )
