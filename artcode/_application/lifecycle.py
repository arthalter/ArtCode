from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path

from artcode._agent import AgentRunner
from artcode._model import DeepSeekModel
from artcode._session import LocalSession
from artcode._skill import LocalSkills
from artcode._subagent import LocalSubagents
from artcode._tool import LocalTools
from artcode._workspace import LocalWorkspace
from artcode.core.agent import RunControl
from artcode.core.application import (
    ApplicationEvent,
    ApplicationOptions,
    ApplicationSnapshot,
    ClearDisplay,
    ErrorOutput,
    ExitRequested,
    Interaction,
    StateOutput,
    TextOutput,
)
from artcode.core.model import Model
from artcode.core.session import CompactionTrigger
from artcode.core.skill import SkillMode
from artcode.core.tool import PermissionMode, RunMode, ShellPolicy
from artcode.core.workspace import DiscardConfirmation

from .commands import HELP, split_command
from .config import LoadedConfig, load_config
from .events import application_event


class LocalApplication:
    def __init__(
        self,
        options: ApplicationOptions,
        config: LoadedConfig,
        workspace: LocalWorkspace,
        model: Model,
        tools: LocalTools,
        session: LocalSession,
        skills: LocalSkills,
        subagents: LocalSubagents,
        interaction: Interaction | None,
    ) -> None:
        self.options = options
        self.config = config
        self.workspace = workspace
        self.model = model
        self.tools = tools
        self.session = session
        self.skills = skills
        self.subagents = subagents
        self.interaction = interaction
        self._control: RunControl | None = None
        self._closed = False
        self._running = False
        self._last_snapshot: ApplicationSnapshot | None = None
        self._cleanup_task = asyncio.create_task(
            self._periodic_worktree_cleanup(), name="artcode-worktree-cleanup"
        )

    @classmethod
    async def create(
        cls,
        options: ApplicationOptions,
        *,
        interaction: Interaction | None = None,
        model: Model | None = None,
    ) -> LocalApplication:
        project_config = options.workspace / ".artcode" / "config.yml"
        config = load_config(options.config_path, project_config)
        workspace = LocalWorkspace(options.workspace)
        selected_model = model or DeepSeekModel(config.model)
        tools = LocalTools(
            permission_mode=config.permission_mode,
            shell_policy=config.shell_policy,
            rules_path=options.workspace / ".artcode" / "ch14" / "permissions.yml",
        )
        session = None
        subagents = None
        try:
            await tools.start_mcp(
                workspace,
                config.user_mcp,
                config.project_mcp,
                loading=config.mcp_loading,
                approver=interaction,
            )
            workspace.cleanup_worktrees(active_task_ids=set())
            session = LocalSession(
                options.workspace,
                options.session,
                user_home=options.artcode_home,
                context_window_tokens=config.context_window_tokens,
            )
            subagents = LocalSubagents(
                options.workspace / ".artcode" / "agents",
                options.artcode_home / "agents",
                Path(__file__).parents[1] / "_subagent" / "builtin",
                workspace=workspace,
                tools=tools,
                model_factory=lambda _: selected_model,
                model_tiers=config.model_tiers,
                background_tools=config.background_tools,
            )
            tools.register_subagents(subagents)
            skills = LocalSkills(
                options.workspace / ".artcode" / "skills",
                options.artcode_home / "skills",
                Path(__file__).parents[1] / "_skill" / "builtin",
                extension_roots=tuple(
                    path / "skills"
                    for path in sorted((options.artcode_home / "plugins").glob("*"))
                    if path.is_dir() and not path.is_symlink()
                ),
                known_tools=lambda: {
                    item.name for item in tools.open_run(workspace, RunMode.CHAT).descriptors
                },
                available_models=lambda: {
                    config.model.model,
                    *config.model_tiers.values(),
                },
            )
            skills.refresh()
            subagents.refresh_roles()
            return cls(
                options,
                config,
                workspace,
                selected_model,
                tools,
                session,
                skills,
                subagents,
                interaction,
            )
        except BaseException:
            if subagents is not None:
                await subagents.close()
            if session is not None:
                await session.aclose()
            await tools.close()
            await selected_model.close()
            await workspace.aclose()
            raise

    async def handle(self, text: str) -> tuple[ApplicationEvent, ...]:
        return tuple([event async for event in self.stream(text)])

    async def stream(self, text: str):
        if self._closed:
            yield ErrorOutput("Application 已关闭。")
            return
        if not isinstance(text, str):
            yield ErrorOutput("输入必须是文本。")
            return
        if text.startswith("/plan"):
            command, rest = split_command(text)
            if command == "/plan":
                async for event in self._run_goal_stream(rest, RunMode.PLAN):
                    yield event
                return
        if text.startswith("/act"):
            command, rest = split_command(text)
            if command == "/act":
                plan = self.session.snapshot().latest_plan
                if plan is None:
                    yield ErrorOutput("没有最近一次成功计划。")
                    return
                goal = f"执行以下计划：\n{plan}"
                if rest:
                    goal += f"\n新增约束：\n{rest}"
                async for event in self._run_goal_stream(goal, RunMode.ACT):
                    yield event
                return
        if text.startswith("/"):
            for event in await self._command(text):
                yield event
            return
        async for event in self._run_goal_stream(text, RunMode.CHAT):
            yield event

    def snapshot(self) -> ApplicationSnapshot:
        if self._closed and self._last_snapshot is not None:
            return replace(self._last_snapshot, running=False, closed=True)
        return ApplicationSnapshot(
            self.workspace.root,
            self.session.snapshot(),
            self.tools.state(),
            self.skills.snapshot(),
            self.subagents.list(),
            self._running,
            self._closed,
        )

    def cancel_current(self) -> bool:
        if self._control is None:
            return False
        self._control.cancel()
        return True

    def background_current_task(self) -> bool:
        for task in reversed(self.subagents.list()):
            if task.state.value in {"queued", "running"} and not task.background:
                self.subagents.background(task.id)
                return True
        return False

    async def close(self) -> None:
        if self._closed:
            return
        self.cancel_current()
        self._cleanup_task.cancel()
        await asyncio.gather(self._cleanup_task, return_exceptions=True)
        await self.subagents.close()
        await self.session.wait_memory_idle()
        self._last_snapshot = self.snapshot()
        self.session.close()
        await self.tools.close()
        await self.model.close()
        await self.workspace.aclose()
        self._closed = True

    async def _run_goal(self, goal: str, mode: RunMode) -> tuple[ApplicationEvent, ...]:
        return tuple([event async for event in self._run_goal_stream(goal, mode)])

    async def _run_goal_stream(self, goal: str, mode: RunMode):
        if not goal.strip():
            yield ErrorOutput("Run 目标不能为空。")
            return
        self._inject_task_notifications()
        selected = self.skills.select(goal)
        if selected.ok and selected.mode is SkillMode.ISOLATED:
            try:
                result = await self.skills.run_isolated(
                    selected.name,
                    goal,
                    parent=self.session,
                    workspace=self.workspace,
                    model=self.model,
                    tools=self.tools,
                )
            except Exception as exc:
                yield ErrorOutput(str(exc))
                return
            yield TextOutput(result.summary)
            yield StateOutput("isolated_skill", result)
            return
        frozen = self.skills.freeze()
        run_tools = self.tools.open_run(
            self.workspace,
            mode,
            allowed_tools=frozen.allowed_tools,
        )
        try:
            lease = await self.session.prepare_run(
                goal,
                run_tools,
                contributions=frozen.contributions,
                model_for_compaction=self.model,
            )
            dispatched = self.session.dispatch_run(lease)
        except Exception as exc:
            yield ErrorOutput(str(exc))
            return
        self._control = RunControl()
        self._running = True
        try:
            async for event in AgentRunner(
                self.model,
                self.tools,
                self.session,
                approver=self.interaction,
                memory_model=self.model,
            ).run(dispatched, control=self._control):
                converted = application_event(event)
                if converted is not None:
                    yield converted
        finally:
            self._running = False
            self._control = None

    async def _command(self, text: str) -> tuple[ApplicationEvent, ...]:
        command, rest = split_command(text)
        if command == "/help":
            return (TextOutput(HELP),)
        if command == "/exit":
            active = tuple(
                task for task in self.subagents.list()
                if task.state.value in {"queued", "running"}
            )
            if active:
                chooser = getattr(self.interaction, "choose_active_task_exit", None)
                if not callable(chooser):
                    return (ErrorOutput("仍有活动 Task；请先等待或取消。"),)
                choice = await chooser(active)
                if choice == "return":
                    return (StateOutput("tasks", active),)
                if choice == "wait":
                    for task in active:
                        await self.subagents.wait(task.id)
                elif choice == "cancel":
                    for task in active:
                        await self.subagents.cancel(task.id)
                else:
                    return (ErrorOutput("退出选择无效，已返回 ArtCode。"),)
            await self.close()
            return (ExitRequested(),)
        if command == "/plan":
            return await self._run_goal(rest, RunMode.PLAN)
        if command == "/act":
            plan = self.session.snapshot().latest_plan
            if plan is None:
                return (ErrorOutput("没有最近一次成功计划。"),)
            goal = f"执行以下计划：\n{plan}"
            if rest:
                goal += f"\n新增约束：\n{rest}"
            return await self._run_goal(goal, RunMode.ACT)
        if command == "/compact":
            report = await self.session.compact(self.model, CompactionTrigger.MANUAL)
            return (StateOutput("compaction", report),)
        if command == "/permissions":
            if not rest:
                return (StateOutput("permission", self.tools.state()),)
            try:
                state = self.tools.set_permission_mode(PermissionMode(rest))
            except (TypeError, ValueError) as exc:
                return (ErrorOutput(str(exc)),)
            return (StateOutput("permission", state),)
        if command == "/sandbox":
            if not rest:
                return (StateOutput("permission", self.tools.state()),)
            values = {
                "auto": ShellPolicy.SANDBOX_AUTO,
                "ask": ShellPolicy.SANDBOX_ASK,
                "off": ShellPolicy.EXPLICIT_UNSAFE,
            }
            if rest not in values:
                return (ErrorOutput("sandbox 只能是 auto、ask 或 off。"),)
            return (StateOutput("permission", self.tools.set_shell_policy(values[rest])),)
        if command == "/skills":
            return (StateOutput("skills", self.skills.refresh()),)
        if command == "/clear":
            self.skills.clear()
            return (ClearDisplay(),)
        if command == "/skill":
            name, _, skill_input = rest.partition(" ")
            activation = self.skills.activate(name)
            if not activation.ok:
                return (ErrorOutput(activation.message),)
            if not skill_input:
                return (StateOutput("skill", activation),)
            if activation.mode is SkillMode.ISOLATED:
                result = await self.skills.run_isolated(
                    activation.name,
                    skill_input,
                    parent=self.session,
                    workspace=self.workspace,
                    model=self.model,
                    tools=self.tools,
                )
                return (TextOutput(result.summary), StateOutput("isolated_skill", result))
            return await self._run_goal(skill_input, RunMode.CHAT)
        if command == "/tasks":
            return (StateOutput("tasks", self.subagents.list()),)
        if command == "/task":
            try:
                return (StateOutput("task", self.subagents.get(rest)),)
            except ValueError as exc:
                return (ErrorOutput(str(exc)),)
        if command == "/task-cancel":
            try:
                return (StateOutput("task", await self.subagents.cancel(rest)),)
            except ValueError as exc:
                return (ErrorOutput(str(exc)),)
        if command == "/task-background":
            try:
                return (StateOutput("task", self.subagents.background(rest)),)
            except ValueError as exc:
                return (ErrorOutput(str(exc)),)
        if command == "/status":
            return (StateOutput("application", self.snapshot()),)
        if command == "/session":
            return (StateOutput("session", self.session.snapshot()),)
        if command == "/memory":
            snapshot = self.session.snapshot()
            return (StateOutput("memory", (snapshot.memory_pending, snapshot.last_memory_report)),)
        if command == "/worktrees":
            current = tuple(task.handoff for task in self.subagents.list() if task.handoff)
            managed = self.workspace.list_managed_worktrees()
            combined = tuple(dict.fromkeys((*current, *managed)))
            return (StateOutput("worktrees", combined),)
        if command == "/worktree-discard":
            try:
                task = self.subagents.get(rest)
                if task.handoff is None or not task.handoff.retained:
                    return (ErrorOutput("Task 没有保留的 Worktree。"),)
                lease = self.workspace.find_worktree(task.id)
                if lease is None:
                    return (ErrorOutput("Worktree 归属不可验证，拒绝丢弃。"),)
                if self.interaction is None or not await self.interaction.confirm_worktree_discard(task.handoff):
                    return (ErrorOutput("用户取消了危险丢弃。"),)
                self.workspace.discard_worktree(
                    lease,
                    DiscardConfirmation(lease.task_id, str(lease.path), lease.branch),
                )
                return (StateOutput("worktree_discarded", str(lease.path)),)
            except ValueError as exc:
                return (ErrorOutput(str(exc)),)
        return (ErrorOutput(f"未知命令：{command}"),)

    def _inject_task_notifications(self) -> None:
        for notice in self.subagents.take_notifications():
            payload = {
                "task_id": notice.task_id,
                "state": notice.state.value,
                "result": notice.result,
                "usage": {
                    "input": notice.usage.input_tokens,
                    "output": notice.usage.output_tokens,
                },
                "handoff": str(notice.handoff.path) if notice.handoff else None,
                "truncated": notice.truncated,
            }
            self.session.add_notice(
                "<task-notification>\n"
                + json.dumps(payload, ensure_ascii=False)
                + "\n</task-notification>"
            )

    async def _periodic_worktree_cleanup(self) -> None:
        try:
            while True:
                await asyncio.sleep(60 * 60)
                active = {
                    task.id
                    for task in self.subagents.list()
                    if task.state.value in {"queued", "running"}
                }
                self.workspace.cleanup_worktrees(active_task_ids=active)
        except asyncio.CancelledError:
            return
