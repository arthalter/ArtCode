from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from artcode.commands.base import DisplayMode
from artcode.permissions import PermissionState

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
