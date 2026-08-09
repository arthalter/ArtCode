from __future__ import annotations

import asyncio
import signal
from dataclasses import dataclass, field
from dataclasses import replace
from typing import Protocol

from artcode.agent import (
    NORMAL_AGENT_MODE,
    PLAN_MODE,
    AgentEvent,
    AgentEventType,
    AgentLoop,
    AgentRunRequest,
    PlanMemory,
    TokenUsage,
)
from artcode.commands import (
    CommandDispatcher,
    CommandFlow,
    CommandRegistry,
    DisplayMode,
    InputRoute,
    create_default_registry,
    parse_input,
)
from artcode.config import ArtCodeConfig
from artcode.conversation import ConversationContext
from artcode.providers.base import StreamingProvider
from artcode.permissions import (
    ApprovalChoice,
    ApprovalRequest,
    PermissionEngine,
    PermissionMode,
    PermissionState,
    RuleWriter,
    ShellPolicy,
)
from artcode.tools import (
    AllowedPathPolicy,
    ToolExecutionContext,
    ToolPreview,
    ToolRegistry,
    ToolResult,
    create_default_tool_registry,
)
from artcode.tui import UserRequestedExit
from artcode.workspace import Workspace
from artcode.agent.tools import ToolBatchExecutor
from artcode.context_management import ContextManager
from artcode.prompting.assembler import PromptRequestAssembler
from artcode.persistence import PersistenceCoordinator
from artcode.runtime.state import RuntimeStatusSnapshot, StartupStatusSnapshot


class TuiApp(Protocol):
    def show_startup(self, status) -> None:
        ...

    async def read_input(self, model: str) -> str:
        ...

    def show_help(self, message: str) -> None:
        ...

    def show_error(self, error) -> None:
        ...

    def show_cancelled(self) -> None:
        ...

    def show_exit(self) -> None:
        ...

    def show_user_label(self) -> None:
        ...

    def show_assistant_label(self) -> None:
        ...

    def stream_delta(self, text: str) -> None:
        ...

    def finish_assistant_message(self) -> None:
        ...

    def show_tool_preview(self, preview: ToolPreview) -> None:
        ...

    async def confirm_tool_execution(self, preview: ToolPreview) -> bool:
        ...

    def show_tool_result_summary(self, result: ToolResult) -> None:
        ...

    def show_agent_iteration(self, current: int, maximum: int) -> None:
        ...

    def show_tool_calls_received(self, count: int) -> None:
        ...

    def show_tool_batch_started(self, batch_index: int, safety: str, count: int) -> None:
        ...

    def show_token_usage(
        self,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        total_tokens: int | None = None,
        cached_tokens: int | None = None,
        cache_miss_tokens: int | None = None,
    ) -> None:
        ...

    def show_agent_stopped(self, reason: str, message: str = "") -> None:
        ...

    def show_context_status(self, payload: dict) -> None:
        ...

    def show_persistence_status(self, payload: dict) -> None:
        ...

    def set_display_mode(self, mode: DisplayMode) -> None:
        ...

    def clear_screen(self) -> None:
        ...

    def show_runtime_status(self, snapshot: RuntimeStatusSnapshot) -> None:
        ...


@dataclass
class ArtCodeRuntime:
    config: ArtCodeConfig
    provider: StreamingProvider
    conversation: ConversationContext
    tui: TuiApp
    tool_registry: ToolRegistry | None = None
    tool_context: ToolExecutionContext | None = None
    commands: CommandRegistry = field(default_factory=create_default_registry)
    plan_memory: PlanMemory | None = None
    agent_loop: AgentLoop | None = None
    workspace: Workspace | None = None
    permission_state: PermissionState = field(default_factory=PermissionState)
    permission_engine: PermissionEngine | None = None
    rule_writer: RuleWriter | None = None
    context_manager: ContextManager | None = None
    request_assembler: PromptRequestAssembler | None = None
    persistence: PersistenceCoordinator | None = None
    command_dispatcher: CommandDispatcher = field(init=False)
    _display_mode: DisplayMode = field(init=False, default=DisplayMode.DEFAULT)
    _last_token_usage: TokenUsage | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        self.command_dispatcher = CommandDispatcher(self.commands)
        if self.tool_registry is None:
            self.tool_registry = create_default_tool_registry()
        if self.tool_context is None:
            selected = self.workspace or Workspace.from_path(self.config.workspace)
            policy = AllowedPathPolicy((selected.root,))
            self.tool_context = ToolExecutionContext(policy, default_cwd=selected.root)
        if self.plan_memory is None:
            self.plan_memory = self.persistence.plan_memory if self.persistence is not None else PlanMemory()
        if self.persistence is not None:
            self.persistence.add_memory_callback(self._show_memory_report)
        if self.agent_loop is None:
            executor = ToolBatchExecutor(
                self.tool_registry,
                self.tool_context,
                permission_engine=self.permission_engine,
                permission_state=self.permission_state,
                approver=self if self.permission_engine is not None else None,
                rule_writer=self.rule_writer,
            )
            self.agent_loop = AgentLoop(
                provider=self.provider,
                conversation=self.conversation,
                tool_registry=self.tool_registry,
                tool_context=self.tool_context,
                plan_memory=self.plan_memory,
                tool_executor=executor,
                context_manager=self.context_manager,
                request_assembler=self.request_assembler,
                natural_turn_observer=(
                    self.persistence.turn_observer if self.persistence is not None else None
                ),
                session_id=(
                    self.persistence.status.session_id if self.persistence is not None else "ephemeral"
                ),
            )

    async def run(self) -> int:
        status = StartupStatusSnapshot.from_config(self.config)
        if self.workspace is not None:
            status = replace(
                status,
                workspace=str(self.workspace.root),
                permission_mode=self.permission_state.mode.value,
                shell_policy=self.permission_state.shell_policy.value,
                seatbelt_status=(
                    "self-test passed"
                    if self.tool_context is not None
                    and self.tool_context.seatbelt is not None
                    and self.tool_context.seatbelt.self_tested
                    else "not initialized"
                ),
            )
        if self.persistence is not None:
            persistent = self.persistence.status
            status = replace(
                status,
                session_id=persistent.session_id,
                session_state=(
                    "restored" if persistent.restored else (
                        "new (latest locked)" if persistent.default_locked_new_session else "new"
                    )
                ),
                recovered_messages=persistent.recovered_messages,
                bad_session_lines=persistent.bad_line_count,
                session_truncated=persistent.truncated,
                instruction_bytes=persistent.instruction_bytes,
                instruction_issues=persistent.instruction_issues,
                user_active_notes=persistent.user_active_notes,
                project_active_notes=persistent.project_active_notes,
            )
        self.tui.show_startup(status)
        while True:
            try:
                user_input = await self.tui.read_input(self.config.model)
            except UserRequestedExit:
                self.tui.show_exit()
                return 0

            parsed = parse_input(user_input)
            if parsed.route is InputRoute.EMPTY:
                continue

            if parsed.route is InputRoute.COMMAND:
                assert parsed.invocation is not None
                flow = await self.command_dispatcher.dispatch(parsed.invocation, self)
                if flow is CommandFlow.EXIT:
                    self.tui.show_exit()
                    return 0
                continue

            await self._run_agent(parsed.message, NORMAL_AGENT_MODE)

    def show_command_message(self, message: str) -> None:
        self.tui.show_help(message)

    def clear_screen(self) -> None:
        handler = getattr(self.tui, "clear_screen", None)
        if callable(handler):
            handler()

    def set_display_mode(self, mode: DisplayMode) -> None:
        self._display_mode = mode
        handler = getattr(self.tui, "set_display_mode", None)
        if callable(handler):
            handler(mode)

    def get_token_usage(self) -> TokenUsage | None:
        return self._last_token_usage

    def refresh_status(self) -> None:
        persistence_status = self.persistence.status if self.persistence is not None else None
        session_state = "不可用"
        if persistence_status is not None:
            session_state = (
                "restored"
                if persistence_status.restored
                else (
                    "new (latest locked)"
                    if persistence_status.default_locked_new_session
                    else "new"
                )
            )
        seatbelt = self.tool_context.seatbelt if self.tool_context is not None else None
        if seatbelt is None:
            seatbelt_status = "not initialized"
        elif seatbelt.self_tested:
            seatbelt_status = "self-test passed"
        else:
            seatbelt_status = "initialized"
        estimated = self.agent_loop.estimate_next_request(NORMAL_AGENT_MODE)
        workspace = self.workspace.root if self.workspace is not None else self.config.workspace
        snapshot = RuntimeStatusSnapshot(
            model=self.config.model,
            workspace=str(workspace) if workspace is not None else "",
            display_mode=self._display_mode,
            permission_mode=self.permission_state.mode.value,
            shell_policy=self.permission_state.shell_policy.value,
            seatbelt_status=seatbelt_status,
            session_id=persistence_status.session_id if persistence_status is not None else None,
            session_state=session_state,
            estimated_context_tokens=estimated,
            context_window_tokens=self.config.context.window_tokens,
            last_token_usage=self._last_token_usage,
        )
        handler = getattr(self.tui, "show_runtime_status", None)
        if callable(handler):
            handler(snapshot)
        else:
            self.tui.show_help(str(snapshot))

    async def send_user_message(self, content: str, mode) -> None:
        await self._run_agent(content, mode)

    async def compact_context(self) -> None:
        async for event in self.agent_loop.compact_context():
            self._handle_agent_event(event)

    def get_recent_plan(self) -> str | None:
        return self.plan_memory.get() if self.plan_memory is not None else None

    async def request_approval(self, request: ApprovalRequest) -> ApprovalChoice:
        handler = getattr(self.tui, "request_approval", None)
        if callable(handler):
            return await handler(request)
        preview = ToolPreview(request.tool_name, request.source, request.target, True)
        allowed = await self.tui.confirm_tool_execution(preview)
        return ApprovalChoice.ALLOW_ONCE if allowed else ApprovalChoice.DENY_ONCE

    async def request_mcp_approval(self, preview: ToolPreview) -> bool:
        handler = getattr(self.tui, "confirm_mcp_tool", None)
        if callable(handler):
            executor = getattr(self.agent_loop, "tool_executor", None)
            return await handler(preview, bool(getattr(executor, "plan_mode", False)))
        return await self.tui.confirm_tool_execution(preview)

    def handle_permission(self, argument: str) -> None:
        if not argument:
            self.tui.show_help(
                f"当前权限模式：{self.permission_state.mode.value}；可选：default、edit、full"
            )
            return
        try:
            self.permission_state.mode = PermissionMode(argument.lower())
        except ValueError:
            self.tui.show_help("权限模式只能是 default、edit 或 full。")
            return
        self.tui.show_help(f"权限模式已切换为：{self.permission_state.mode.value}")

    async def handle_sandbox(self, argument: str) -> None:
        if not argument:
            self.tui.show_help(
                f"当前 Shell 策略：{self.permission_state.shell_policy.value}；可选：auto、ask、off"
            )
            return
        try:
            selected = ShellPolicy(argument.lower())
        except ValueError:
            self.tui.show_help("Shell 策略只能是 auto、ask 或 off。")
            return
        if selected is ShellPolicy.UNSANDBOXED_ASK:
            confirm = getattr(self.tui, "confirm_unsandboxed", None)
            if callable(confirm):
                allowed = await confirm()
            else:
                allowed = await self.tui.confirm_tool_execution(
                    ToolPreview(
                        "run_command",
                        "关闭 Seatbelt 后，命令只受危险命令检查和人工授权保护。",
                        "当前运行",
                        True,
                    )
                )
            if not allowed:
                self.tui.show_help("已取消切换，Shell 策略保持不变。")
                return
        self.permission_state.shell_policy = selected
        if self.tool_context is not None:
            object.__setattr__(self.tool_context, "shell_policy", selected)
        self.tui.show_help(f"Shell 策略已切换为：{selected.value}")

    async def _run_agent(self, user_content, mode) -> None:
        display_mode = DisplayMode.PLAN if mode == PLAN_MODE else DisplayMode.DEFAULT
        self.set_display_mode(display_mode)
        self.tui.show_user_label()
        self.tui.show_assistant_label()
        request = AgentRunRequest(user_content=user_content, mode=mode)
        task = asyncio.create_task(self._consume_agent_events(request))
        self._install_generation_cancel_handler(task)
        try:
            await task
        except asyncio.CancelledError:
            self.tui.show_cancelled()
        finally:
            self._remove_generation_cancel_handler()
            self.set_display_mode(DisplayMode.DEFAULT)

    async def _consume_agent_events(self, request: AgentRunRequest) -> None:
        previous_error = self.conversation.last_observer_error
        async for event in self.agent_loop.run(request):
            self._handle_agent_event(event)
        current_error = self.conversation.last_observer_error
        if current_error is not None and current_error is not previous_error:
            self._show_persistence_payload(
                {
                    "kind": "journal",
                    "status": "failed",
                    "message": "当前轮可继续，但下次恢复可能不完整。",
                }
            )

    def _handle_agent_event(self, event: AgentEvent) -> None:
        if event.type == AgentEventType.ITERATION_STARTED:
            self.tui.show_agent_iteration(event.payload["current"], event.payload["maximum"])
        elif event.type == AgentEventType.TEXT_DELTA:
            self.tui.stream_delta(event.payload["text"])
        elif event.type == AgentEventType.MODEL_TURN_COMPLETED:
            if event.payload.get("text"):
                self.tui.finish_assistant_message()
        elif event.type == AgentEventType.TOOL_CALLS_RECEIVED:
            self.tui.show_tool_calls_received(event.payload["count"])
        elif event.type == AgentEventType.TOOL_BATCH_STARTED:
            self.tui.show_tool_batch_started(event.payload["index"], event.payload["safety"], event.payload["count"])
        elif event.type == AgentEventType.TOOL_RESULT:
            self.tui.show_tool_result_summary(event.payload["result"])
        elif event.type == AgentEventType.TOKEN_USAGE:
            self._last_token_usage = TokenUsage.from_event_payload(event.payload)
            self.tui.show_token_usage(
                event.payload.get("prompt_tokens"),
                event.payload.get("completion_tokens"),
                event.payload.get("total_tokens"),
                event.payload.get("cached_tokens"),
                event.payload.get("cache_miss_tokens"),
            )
        elif event.type == AgentEventType.STOPPED:
            self.tui.show_agent_stopped(event.payload["reason"], event.payload.get("message", ""))
            if event.payload["reason"] == "user_cancelled":
                self.tui.show_cancelled()
        elif event.type == AgentEventType.CONTEXT_STATUS:
            handler = getattr(self.tui, "show_context_status", None)
            if callable(handler):
                handler(event.payload)

    def show_sessions(self) -> None:
        if self.persistence is None:
            self.tui.show_help("会话持久化尚未启用。")
            return
        current = self.persistence.status.session_id
        lines = ["最近会话："]
        for item in self.persistence.sessions_summary(20):
            marker = "*" if item.session_id == current else " "
            locked = " [使用中]" if item.locked else ""
            lines.append(
                f"{marker} {item.session_id} | {item.title} | {item.message_count} 条 | "
                f"{item.last_active_at.isoformat()}{locked}"
            )
        if len(lines) == 1:
            lines.append("（无）")
        self.tui.show_help("\n".join(lines))

    def show_memory(self) -> None:
        if self.persistence is None:
            self.tui.show_help("长期记忆尚未启用。")
            return
        summary = self.persistence.memory_summary()
        report = summary["last_report"]
        last = report.status if report is not None else "尚无后台更新"
        self.tui.show_help(
            "\n".join(
                (
                    f"用户级记忆：{summary['user_path']}（active={summary['user_active']} superseded={summary['user_superseded']} issues={summary['user_issues']}）",
                    f"项目级记忆：{summary['project_path']}（active={summary['project_active']} superseded={summary['project_superseded']} issues={summary['project_issues']}）",
                    f"最近更新：{last}",
                )
            )
        )

    def _show_memory_report(self, report) -> None:
        self._show_persistence_payload(
            {
                "kind": "memory",
                "status": report.status,
                "created": report.created,
                "updated": report.updated,
                "superseded": report.superseded,
                "rejected": report.rejected,
                "message": report.message,
            }
        )

    def _show_persistence_payload(self, payload: dict) -> None:
        handler = getattr(self.tui, "show_persistence_status", None)
        if callable(handler):
            handler(payload)
        elif payload.get("message"):
            self.tui.show_help(payload["message"])

    def _install_generation_cancel_handler(self, task: asyncio.Task[None]) -> None:
        try:
            loop = asyncio.get_running_loop()
            loop.add_signal_handler(signal.SIGINT, task.cancel)
        except (NotImplementedError, RuntimeError):
            return

    def _remove_generation_cancel_handler(self) -> None:
        try:
            loop = asyncio.get_running_loop()
            loop.remove_signal_handler(signal.SIGINT)
        except (NotImplementedError, RuntimeError):
            return
