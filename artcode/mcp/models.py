from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Mapping


class TransportKind(StrEnum):
    STDIO = "stdio"
    STREAMABLE_HTTP = "streamable_http"


class ServerSource(StrEnum):
    USER = "user"
    PROJECT = "project"


class ServerState(StrEnum):
    DISABLED = "disabled"
    REJECTED = "rejected"
    INVALID = "invalid"
    CONNECTING = "connecting"
    READY = "ready"
    UNAVAILABLE = "unavailable"
    CLOSED = "closed"


class FailureStage(StrEnum):
    CONFIG = "config"
    APPROVAL = "approval"
    TRANSPORT = "transport"
    INITIALIZE = "initialize"
    DISCOVERY = "discovery"
    REGISTRATION = "registration"
    CALL = "call"
    CLOSE = "close"


@dataclass(frozen=True)
class McpServerConfig:
    name: str
    transport: TransportKind
    source: ServerSource
    enabled: bool = True
    command: str | None = None
    args: tuple[str, ...] = ()
    env: Mapping[str, str] = field(default_factory=dict)
    url: str | None = None
    headers: Mapping[str, str] = field(default_factory=dict)
    referenced_variables: tuple[str, ...] = ()


@dataclass(frozen=True)
class McpConfigIssue:
    server_name: str
    message: str
    source: ServerSource


@dataclass(frozen=True)
class McpServerReport:
    name: str
    source: ServerSource
    state: ServerState
    tool_count: int = 0
    failure_stage: FailureStage | None = None
    detail: str = ""
    truncated: bool = False


@dataclass(frozen=True)
class McpStartupReport:
    configured_count: int = 0
    server_reports: tuple[McpServerReport, ...] = ()
    registered_tool_count: int = 0

    @property
    def connected_count(self) -> int:
        return sum(report.state is ServerState.READY for report in self.server_reports)

    @property
    def failed_count(self) -> int:
        return sum(
            report.state in {ServerState.INVALID, ServerState.UNAVAILABLE}
            for report in self.server_reports
        )
