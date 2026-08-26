from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from artcode.agent import AgentLoop
from artcode.conversation import ConversationContext
from artcode.tools import ToolEnvironment

from .permissions import SubagentPermissionService
from .models import AgentCreateRequest, RoleDefinition


@dataclass
class SubagentRuntime:
    task_id: str
    request: AgentCreateRequest
    role: RoleDefinition | None
    conversation: ConversationContext
    environment: ToolEnvironment
    loop: AgentLoop
    permissions: SubagentPermissionService
    model_override: str | None
    worktree_lease: object | None = None
    close: Callable[[], None] | None = None
