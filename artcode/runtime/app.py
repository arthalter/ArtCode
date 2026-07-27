from __future__ import annotations

import asyncio
import signal
from dataclasses import dataclass, field
from dataclasses import replace
from typing import Protocol

from artcode.agent import (
    DO_MODE,
    NORMAL_AGENT_MODE,
    PLAN_MODE,
    AgentEvent,
    AgentEventType,
    AgentLoop,
    AgentRunRequest,
    PlanMemory,
)
from artcode.commands import CommandRegistry, create_default_registry
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

    def __post_init__(self) -> None:
        if self.tool_registry is None:
            self.tool_registry = create_default_tool_registry()
        if self.tool_context is None:
            selected = self.workspace or Workspace.from_path(self.config.workspace)
            policy = AllowedPathPolicy((selected.root,))
            self.tool_context = ToolExecutionContext(policy, default_cwd=selected.root)
        if self.plan_memory is None:
            self.plan_memory = PlanMemory()
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
            )

    async def run(self) -> int:
        status = self.config.safe_status()
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
        self.tui.show_startup(status)
        while True:
            try:
                user_input = await self.tui.read_input(self.config.model)
            except UserRequestedExit:
                self.tui.show_exit()
                return 0

            if not user_input.strip():
                continue

            command_result = self.commands.handle(user_input)
            if command_result is not None:
                if command_result.should_exit:
                    self.tui.show_exit()
                    return 0
                if command_result.action == "plan":
                    await self._run_agent(command_result.argument, PLAN_MODE)
                    continue
                if command_result.action == "do":
                    await self._run_do(command_result.argument)
                    continue
                if command_result.action == "permission":
                    self._handle_permission_command(command_result.argument)
                    continue
                if command_result.action == "sandbox":
                    await self._handle_sandbox_command(command_result.argument)
                    continue
                if command_result.message:
                    self.tui.show_help(command_result.message)
                continue

            await self._run_agent(user_input, NORMAL_AGENT_MODE)

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

    def _handle_permission_command(self, argument: str) -> None:
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

    async def _handle_sandbox_command(self, argument: str) -> None:
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

    async def _run_do(self, extra_instruction: str) -> None:
        plan = self.plan_memory.get() if self.plan_memory is not None else None
        if not plan:
            self.tui.show_help("没有最近计划。请先执行 /plan 任务描述。")
            return

        if extra_instruction.strip():
            content = "\n\n".join(
                [
                    "请执行最近计划：",
                    plan,
                    "附加说明：",
                    extra_instruction.strip(),
                ]
            )
        else:
            content = "\n\n".join(["请执行最近计划：", plan])
        await self._run_agent(content, DO_MODE)

    async def _run_agent(self, user_content, mode) -> None:
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

    async def _consume_agent_events(self, request: AgentRunRequest) -> None:
        async for event in self.agent_loop.run(request):
            self._handle_agent_event(event)

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
