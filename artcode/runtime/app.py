from __future__ import annotations

import asyncio
import signal
from dataclasses import dataclass
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
    DisplayMode,
    InputRoute,
    parse_input,
)
from artcode.config import ArtCodeConfig
from artcode.conversation import ConversationContext
from artcode.permissions import (
    PermissionMode,
    ShellPolicy,
)
from artcode.tools import (
    ToolEnvironment,
    ToolResult,
)
from artcode.tui import UserRequestedExit
from artcode.workspace import Workspace
from artcode.mcp import McpStartupReport
from artcode.persistence import MemoryService, SessionService
from artcode.runtime.state import RuntimeState, RuntimeStatusSnapshot, StartupStatusSnapshot
from artcode.skills.execution import SkillExecutionCoordinator
from artcode.skills.service import SkillService
from artcode.background import BackgroundTaskManager
from artcode.background.presentation import render_handoff, render_usage
from artcode.worktrees import WorktreeManager


class TuiApp(Protocol):
    def show_startup(self, status) -> None:
        ...

    def show_mcp_startup(self, report: McpStartupReport) -> None:
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

    async def confirm_unsandboxed(self) -> bool:
        ...

    def show_tool_result_summary(self, result: ToolResult) -> None:
        ...

    def show_agent_iteration(self, current: int, maximum: int | None) -> None:
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
    conversation: ConversationContext
    tui: TuiApp
    workspace: Workspace
    state: RuntimeState
    tool_environment: ToolEnvironment
    plan_memory: PlanMemory
    agent_loop: AgentLoop
    command_dispatcher: CommandDispatcher
    session_service: SessionService
    memory_service: MemoryService
    startup_status: StartupStatusSnapshot
    mcp_report: McpStartupReport
    skill_service: SkillService | None
    task_manager: BackgroundTaskManager | None
    startup_worktree_diagnostics: tuple[str, ...]
    worktree_manager: WorktreeManager | None

    async def run(self) -> int:
        self.tui.show_startup(self.startup_status)
        self.tui.show_mcp_startup(self.mcp_report)
        if self.startup_worktree_diagnostics:
            details = "\n".join(
                f"- {message}" for message in self.startup_worktree_diagnostics
            )
            self.tui.show_help(f"遗留 Worktree 检查：\n{details}")
        self._show_skill_diagnostics()
        while True:
            try:
                user_input = await self.tui.read_input(self.config.model)
            except UserRequestedExit:
                if await self._confirm_exit_with_active_tasks():
                    self.tui.show_exit()
                    return 0
                continue

            parsed = parse_input(user_input)
            if parsed.route is InputRoute.EMPTY:
                continue
            self._show_skill_diagnostics()

            if parsed.route is InputRoute.COMMAND:
                assert parsed.invocation is not None
                if await self._dispatch_skill_command(parsed.invocation):
                    continue
                flow = await self.command_dispatcher.dispatch(parsed.invocation, self)
                if flow is CommandFlow.EXIT:
                    if await self._confirm_exit_with_active_tasks():
                        self.tui.show_exit()
                        return 0
                continue

            await self._run_agent(parsed.message, NORMAL_AGENT_MODE)

    def show_command_message(self, message: str) -> None:
        self.tui.show_help(message)

    def clear_screen(self) -> None:
        self.tui.clear_screen()

    def clear_skills(self) -> None:
        if self.skill_service is not None:
            self.skill_service.clear()

    def show_tasks(self) -> None:
        if self.task_manager is None:
            self.tui.show_help("子 Agent 任务管理器尚未启用。")
            return
        items = self.task_manager.list()
        if not items:
            self.tui.show_help("当前没有子 Agent 任务。")
            return
        now = __import__("time").monotonic()
        lines = ["子 Agent 任务："]
        for item in items:
            since = item.started_at or item.queued_at
            until = item.finished_at or now
            elapsed = max(0.0, until - since)
            retained = (
                "待定"
                if item.worktree_retained is None
                else "是" if item.worktree_retained else "否"
            )
            lines.append(
                f"{item.task_id} type={item.kind} role={item.role_name or '-'} "
                f"status={item.status.value} mode={'后台' if item.background else '前台'} "
                f"running={elapsed:.1f}s worktree={'yes' if item.worktree_required else 'no'} "
                f"retained={retained}"
            )
        self.tui.show_help("\n".join(lines))

    def show_task(self, task_id: str) -> None:
        if self.task_manager is None:
            self.tui.show_help("子 Agent 任务管理器尚未启用。")
            return
        detail = self.task_manager.get(task_id)
        if detail is None:
            self.tui.show_help("找不到指定任务。")
            return
        result = detail.result
        lines = [
            f"任务：{detail.task_id}",
            f"状态：{detail.status.value}",
            f"类型：{detail.kind}；角色：{detail.role_name or '-'}",
            f"错误：{detail.error_message or '-'}",
        ]
        if result is not None:
            lines.extend((
                f"停止原因：{result.stop_reason.value}",
                f"轮次：{result.rounds}",
                f"用量：{render_usage(result.usage)}",
                f"Fork 前缀保真：{('不适用' if result.cache_prefix_preserved is None else str(result.cache_prefix_preserved).lower())}",
                f"结果：\n{result.final_text or '（无）'}",
                "权限事件：\n" + ("\n".join(str(item) for item in result.permission_events) or "（无）"),
                f"Git 交接：{render_handoff(result.handoff)}",
            ))
        self.tui.show_help("\n".join(lines))

    def cancel_task(self, task_id: str) -> None:
        if self.task_manager is None:
            self.tui.show_help("子 Agent 任务管理器尚未启用。")
            return
        if self.task_manager.cancel(task_id):
            self.tui.show_help(f"已请求取消任务：{task_id}。已完成的文件操作不会回滚。")
        else:
            self.tui.show_help("任务不存在或已经结束。")

    async def drop_worktree(self, task_id: str) -> None:
        if self.worktree_manager is None:
            self.tui.show_help("Worktree 管理器尚未启用。")
            return
        try:
            lease = self.worktree_manager.find(task_id)
        except ValueError as exc:
            self.tui.show_help(str(exc))
            return
        if lease is None:
            self.tui.show_help("找不到可丢弃的系统 Worktree（可能已被清理或不属于本仓库）。")
            return
        status = self.worktree_manager.status(lease)
        confirmed = await self.tui.confirm_worktree_discard(
            task_id, lease.path, lease.branch, status
        )
        if not confirmed:
            self.tui.show_help("已取消丢弃，未删除任何内容。")
            return
        try:
            self.worktree_manager.discard(task_id)
        except Exception as exc:
            self.tui.show_error(f"丢弃 Worktree 失败：{exc}")
            return
        self.tui.show_help(
            f"已丢弃 Worktree：{lease.path}（分支 {lease.branch} 与归属元数据已删除）。"
        )

    async def _confirm_exit_with_active_tasks(self) -> bool:
        if self.task_manager is None:
            return True
        active = self.task_manager.active()
        if not active:
            return True
        chooser = getattr(self.tui, "choose_active_task_exit", None)
        if not callable(chooser):
            # Non-interactive ports cannot silently abandon children.
            return False
        choice = await chooser(active)
        if choice == "return":
            return False
        if choice == "wait":
            self.tui.show_help("正在等待全部子 Agent 任务完成……")
            await self.task_manager.wait_all()
            return True
        if choice == "cancel":
            self.tui.show_help("正在取消活动任务并执行 Worktree 成果保护……")
            await self.task_manager.cancel_all()
            return True
        self.tui.show_help("未识别退出选择，已返回 ArtCode。")
        return False

    def _show_skill_diagnostics(self) -> None:
        if self.skill_service is None:
            return
        self.skill_service.refresh()
        diagnostics = self.skill_service.take_unreported_diagnostics()
        if diagnostics:
            self.tui.show_help(
                "Skill 诊断：\n" + "\n".join(item.render() for item in diagnostics)
            )

    def get_dynamic_command_definitions(self) -> tuple[tuple[str, str, str], ...]:
        if self.skill_service is None:
            return ()
        snapshot = self.skill_service.refresh()
        active_names = {item.definition.name for item in snapshot.active}
        return tuple(
            (f"/{item.name}", item.metadata.description, f"/{item.name} [附加要求]")
            for item in snapshot.catalog.definitions
            if item.name in active_names
        )

    def set_display_mode(self, mode: DisplayMode) -> None:
        self.state.set_display_mode(mode)
        self.tui.set_display_mode(mode)

    def get_token_usage(self) -> TokenUsage | None:
        return self.state.last_token_usage

    def refresh_status(self) -> None:
        persistence_status = self.session_service.status
        session_state = (
            "restored"
            if persistence_status.restored
            else (
                "new (latest locked)"
                if persistence_status.default_locked_new_session
                else "new"
            )
        )
        seatbelt = self.tool_environment.seatbelt
        if seatbelt is None:
            seatbelt_status = "not initialized"
        elif seatbelt.self_tested:
            seatbelt_status = "self-test passed"
        else:
            seatbelt_status = "initialized"
        estimated = self.agent_loop.estimate_next_request(NORMAL_AGENT_MODE)
        snapshot = self.state.status_snapshot(
            model=self.config.model,
            workspace=str(self.workspace.root),
            seatbelt_status=seatbelt_status,
            session_id=persistence_status.session_id,
            session_state=session_state,
            estimated_context_tokens=estimated,
            context_window_tokens=self.config.context.window_tokens,
        )
        self.tui.show_runtime_status(snapshot)

    async def send_user_message(self, content: str, mode) -> None:
        await self._run_agent(content, mode)

    async def compact_context(self) -> None:
        async for event in self.agent_loop.compact_context():
            self._handle_agent_event(event)

    def get_recent_plan(self) -> str | None:
        return self.plan_memory.get()

    def handle_permission(self, argument: str) -> None:
        if not argument:
            self.tui.show_help(
                f"当前权限模式：{self.state.permission.mode.value}；可选：default、edit、full"
            )
            return
        try:
            self.state.set_permission_mode(PermissionMode(argument.lower()))
        except ValueError:
            self.tui.show_help("权限模式只能是 default、edit 或 full。")
            return
        self.tui.show_help(f"权限模式已切换为：{self.state.permission.mode.value}")

    async def handle_sandbox(self, argument: str) -> None:
        if not argument:
            self.tui.show_help(
                f"当前 Shell 策略：{self.state.permission.shell_policy.value}；可选：auto、ask、off"
            )
            return
        try:
            selected = ShellPolicy(argument.lower())
        except ValueError:
            self.tui.show_help("Shell 策略只能是 auto、ask 或 off。")
            return
        if selected is ShellPolicy.UNSANDBOXED_ASK:
            allowed = await self.tui.confirm_unsandboxed()
            if not allowed:
                self.tui.show_help("已取消切换，Shell 策略保持不变。")
                return
        self.state.set_shell_policy(selected)
        self.tui.show_help(f"Shell 策略已切换为：{selected.value}")

    async def _run_agent(self, user_content, mode, *, model_override: str | None = None) -> None:
        display_mode = DisplayMode.PLAN if mode == PLAN_MODE else DisplayMode.DEFAULT
        self.set_display_mode(display_mode)
        self.tui.show_user_label()
        self.tui.show_assistant_label()
        request = AgentRunRequest(
            user_content=user_content,
            mode=mode,
            model_override=model_override,
        )
        task = asyncio.create_task(self._consume_agent_events(request))
        self._install_generation_cancel_handler(task)
        try:
            await task
        except asyncio.CancelledError:
            self.tui.show_cancelled()
        finally:
            await self._remove_generation_cancel_handler()
            self.set_display_mode(DisplayMode.DEFAULT)

    async def _dispatch_skill_command(self, invocation) -> bool:
        if self.skill_service is None:
            return False
        name = invocation.normalized_identifier.removeprefix("/")
        outcome = self.skill_service.activate(name)
        if not outcome.ok:
            return False
        definition = outcome.definition
        assert definition is not None
        content = invocation.argument or f"请执行已激活的 Skill：{definition.name}。"
        display_mode = DisplayMode.DEFAULT
        self.set_display_mode(display_mode)
        self.tui.show_user_label()
        self.tui.show_assistant_label()
        coordinator = SkillExecutionCoordinator(self.agent_loop)
        task = asyncio.create_task(self._consume_skill_events(coordinator, definition, content))
        self._install_generation_cancel_handler(task)
        try:
            await task
        except asyncio.CancelledError:
            self.tui.show_cancelled()
        finally:
            await self._remove_generation_cancel_handler()
            self.set_display_mode(DisplayMode.DEFAULT)
        return True

    async def _consume_skill_events(
        self,
        coordinator: SkillExecutionCoordinator,
        definition,
        content: str,
    ) -> None:
        previous_error = self.conversation.last_observer_error
        async for event in coordinator.run(definition, content):
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
            self.state.record_usage(TokenUsage.from_event_payload(event.payload))
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
            self.tui.show_context_status(event.payload)

    def show_sessions(self) -> None:
        current = self.session_service.status.session_id
        lines = ["最近会话："]
        for item in self.session_service.sessions_summary(20):
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
        summary = self.memory_service.status_snapshot()
        report = summary.last_report
        last = report.status if report is not None else "尚无后台更新"
        self.tui.show_help(
            "\n".join(
                (
                    f"用户级记忆：{summary.user_path}（active={summary.user_active} superseded={summary.user_superseded} issues={summary.user_issues}）",
                    f"项目级记忆：{summary.project_path}（active={summary.project_active} superseded={summary.project_superseded} issues={summary.project_issues}）",
                    f"最近更新：{last}",
                )
            )
        )

    def show_memory_report(self, report) -> None:
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
        self.tui.show_persistence_status(payload)

    def _install_generation_cancel_handler(self, task: asyncio.Task[None]) -> None:
        try:
            loop = asyncio.get_running_loop()
            loop.add_signal_handler(signal.SIGINT, task.cancel)
        except (NotImplementedError, RuntimeError):
            pass
        begin_controls = getattr(self.tui, "begin_generation_controls", None)
        if callable(begin_controls):
            begin_controls(task.cancel, self._promote_foreground_task)

    async def _remove_generation_cancel_handler(self) -> None:
        try:
            loop = asyncio.get_running_loop()
            loop.remove_signal_handler(signal.SIGINT)
        except (NotImplementedError, RuntimeError):
            pass
        end_controls = getattr(self.tui, "end_generation_controls", None)
        if callable(end_controls):
            result = end_controls()
            if asyncio.iscoroutine(result):
                await result

    def _promote_foreground_task(self) -> None:
        if self.task_manager is None:
            return
        task_id = self.task_manager.promote_current_foreground()
        if task_id is not None:
            self.tui.show_help(
                f"已将 {task_id} 切换到后台；任务、消息、用量和 Worktree 保持不变。"
            )
