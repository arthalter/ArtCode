from __future__ import annotations

from .base import (
    CommandDefinition,
    CommandExecutionContext,
    CommandFlow,
    CommandInvocation,
    CommandType,
)
from .registry import CommandRegistry


def create_default_registry() -> CommandRegistry:
    registry = CommandRegistry()
    definitions = (
        _definition("/exit", "退出 ArtCode。", ("/exit",), CommandType.LOCAL, _exit),
        _definition("/quit", "退出 ArtCode。", ("/quit",), CommandType.LOCAL, _exit),
        _definition(
            "/help",
            "显示命令总览或单个命令详情。",
            ("/help", "/help /命令"),
            CommandType.LOCAL,
            _help,
            "[/命令]",
        ),
        _definition(
            "/plan",
            "为单行或多行任务生成一次只读计划。",
            ("/plan 任务描述", "/plan 第一行任务\n第二行约束"),
            CommandType.AI,
            _plan,
            "任务描述",
        ),
        _definition(
            "/do",
            "执行最近计划，可附加补充说明。",
            ("/do", "/do 附加说明"),
            CommandType.AI,
            _do,
            "[附加说明]",
        ),
        _definition("/compact", "手动压缩当前上下文。", ("/compact",), CommandType.LOCAL, _compact),
        _definition(
            "/permission",
            "查询或切换权限模式。",
            ("/permission", "/permission default|edit|full"),
            CommandType.UI_STATE,
            _permission,
            "[default|edit|full]",
        ),
        _definition(
            "/sandbox",
            "查询或切换 Shell 沙箱策略。",
            ("/sandbox", "/sandbox auto|ask|off"),
            CommandType.UI_STATE,
            _sandbox,
            "[auto|ask|off]",
        ),
        _definition("/sessions", "显示当前与最近会话。", ("/sessions",), CommandType.LOCAL, _sessions),
        _definition("/memory", "显示长期记忆摘要。", ("/memory",), CommandType.LOCAL, _memory),
        _definition("/tasks", "列出当前子 Agent 任务。", ("/tasks",), CommandType.LOCAL, _tasks),
        _definition("/task", "查看一个子 Agent 任务详情。", ("/task <task-id>",), CommandType.LOCAL, _task, "<task-id>"),
        _definition("/task-cancel", "取消一个尚未结束的子 Agent 任务。", ("/task-cancel <task-id>",), CommandType.LOCAL, _task_cancel, "<task-id>"),
        _definition("/worktree-drop", "确认后永久丢弃一个被保留的系统 Worktree 及其分支。", ("/worktree-drop <task-id>",), CommandType.LOCAL, _worktree_drop, "<task-id>"),
        _definition("/clear", "清空当前终端的可见内容。", ("/clear",), CommandType.UI_STATE, _clear),
        _definition("/status", "显示脱敏运行状态。", ("/status",), CommandType.LOCAL, _status),
    )
    for definition in definitions:
        registry.register(definition)
    return registry


def _definition(
    name: str,
    description: str,
    usage: tuple[str, ...],
    command_type: CommandType,
    handler,
    argument_hint: str | None = None,
    hidden: bool = False,
) -> CommandDefinition:
    return CommandDefinition(
        name=name,
        aliases=(),
        description=description,
        usage=usage,
        command_type=command_type,
        handler=handler,
        argument_hint=argument_hint,
        hidden=hidden,
    )


async def _exit(invocation: CommandInvocation, context: CommandExecutionContext) -> CommandFlow:
    if _reject_argument(invocation, context):
        return CommandFlow.CONTINUE
    return CommandFlow.EXIT


async def _help(invocation: CommandInvocation, context: CommandExecutionContext) -> CommandFlow:
    query = invocation.argument.strip()
    if not query:
        lines = ["可用命令："]
        for definition in context.registry.definitions():
            lines.append(
                f"{definition.name} [{definition.command_type.value}] — "
                f"{definition.description} 用法：{definition.usage[0]}"
            )
        for name, description, usage in _dynamic_commands(context.controller):
            lines.append(f"{name} [ai] — {description} 用法：{usage}")
        context.controller.show_command_message("\n".join(lines))
        return CommandFlow.CONTINUE

    if any(character.isspace() for character in query):
        context.controller.show_command_message("请使用 /help /命令 查看单个命令详情。")
        return CommandFlow.CONTINUE
    definition = context.registry.resolve(query)
    if definition is None:
        dynamic = next(
            (item for item in _dynamic_commands(context.controller) if item[0].lower() == query.lower()),
            None,
        )
        if dynamic is not None:
            name, description, usage = dynamic
            context.controller.show_command_message(
                "\n".join((f"命令：{name}", f"说明：{description}", "类型：ai", f"用法：\n  {usage}"))
            )
            return CommandFlow.CONTINUE
        context.controller.show_command_message(
            f"未知命令：{query}。请使用 /help 查看可用命令。"
        )
        return CommandFlow.CONTINUE

    aliases = "、".join(definition.aliases) if definition.aliases else "无"
    hint = definition.argument_hint or "无"
    usages = "\n".join(f"  {usage}" for usage in definition.usage)
    context.controller.show_command_message(
        "\n".join(
            (
                f"命令：{definition.name}",
                f"说明：{definition.description}",
                f"类型：{definition.command_type.value}",
                f"别名：{aliases}",
                f"参数：{hint}",
                f"隐藏：{'是' if definition.hidden else '否'}",
                "用法：",
                usages,
            )
        )
    )
    return CommandFlow.CONTINUE


async def _plan(invocation: CommandInvocation, context: CommandExecutionContext) -> CommandFlow:
    from artcode.agent.modes import PLAN_MODE

    if not invocation.argument:
        context.controller.show_command_message("请使用 /plan 任务描述。")
        return CommandFlow.CONTINUE
    await context.controller.send_user_message(invocation.argument, PLAN_MODE)
    return CommandFlow.CONTINUE


async def _do(invocation: CommandInvocation, context: CommandExecutionContext) -> CommandFlow:
    from artcode.agent.modes import DO_MODE

    plan = context.controller.get_recent_plan()
    if not plan:
        context.controller.show_command_message("没有最近计划。请先执行 /plan 任务描述。")
        return CommandFlow.CONTINUE
    parts = ["请执行最近计划：", plan]
    if invocation.argument:
        parts.extend(("附加说明：", invocation.argument))
    await context.controller.send_user_message("\n\n".join(parts), DO_MODE)
    return CommandFlow.CONTINUE


async def _compact(invocation: CommandInvocation, context: CommandExecutionContext) -> CommandFlow:
    if _reject_argument(invocation, context):
        return CommandFlow.CONTINUE
    await context.controller.compact_context()
    return CommandFlow.CONTINUE


async def _permission(invocation: CommandInvocation, context: CommandExecutionContext) -> CommandFlow:
    context.controller.handle_permission(invocation.argument)
    return CommandFlow.CONTINUE


async def _sandbox(invocation: CommandInvocation, context: CommandExecutionContext) -> CommandFlow:
    await context.controller.handle_sandbox(invocation.argument)
    return CommandFlow.CONTINUE


async def _sessions(invocation: CommandInvocation, context: CommandExecutionContext) -> CommandFlow:
    if _reject_argument(invocation, context):
        return CommandFlow.CONTINUE
    context.controller.show_sessions()
    return CommandFlow.CONTINUE


async def _memory(invocation: CommandInvocation, context: CommandExecutionContext) -> CommandFlow:
    if _reject_argument(invocation, context):
        return CommandFlow.CONTINUE
    context.controller.show_memory()
    return CommandFlow.CONTINUE


async def _tasks(invocation: CommandInvocation, context: CommandExecutionContext) -> CommandFlow:
    if _reject_argument(invocation, context):
        return CommandFlow.CONTINUE
    context.controller.show_tasks()
    return CommandFlow.CONTINUE


async def _task(invocation: CommandInvocation, context: CommandExecutionContext) -> CommandFlow:
    if not invocation.argument or any(character.isspace() for character in invocation.argument):
        context.controller.show_command_message("用法：/task <task-id>")
        return CommandFlow.CONTINUE
    context.controller.show_task(invocation.argument)
    return CommandFlow.CONTINUE


async def _task_cancel(invocation: CommandInvocation, context: CommandExecutionContext) -> CommandFlow:
    if not invocation.argument or any(character.isspace() for character in invocation.argument):
        context.controller.show_command_message("用法：/task-cancel <task-id>")
        return CommandFlow.CONTINUE
    context.controller.cancel_task(invocation.argument)
    return CommandFlow.CONTINUE


async def _worktree_drop(invocation: CommandInvocation, context: CommandExecutionContext) -> CommandFlow:
    if not invocation.argument or any(character.isspace() for character in invocation.argument):
        context.controller.show_command_message("用法：/worktree-drop <task-id>")
        return CommandFlow.CONTINUE
    await context.controller.drop_worktree(invocation.argument)
    return CommandFlow.CONTINUE


async def _clear(invocation: CommandInvocation, context: CommandExecutionContext) -> CommandFlow:
    if _reject_argument(invocation, context):
        return CommandFlow.CONTINUE
    context.controller.clear_screen()
    clear_skills = getattr(context.controller, "clear_skills", None)
    if callable(clear_skills):
        clear_skills()
    return CommandFlow.CONTINUE


def _dynamic_commands(controller) -> tuple[tuple[str, str, str], ...]:
    provider = getattr(controller, "get_dynamic_command_definitions", None)
    if not callable(provider):
        return ()
    result = provider()
    return result if isinstance(result, tuple) else ()


async def _status(invocation: CommandInvocation, context: CommandExecutionContext) -> CommandFlow:
    if _reject_argument(invocation, context):
        return CommandFlow.CONTINUE
    context.controller.refresh_status()
    return CommandFlow.CONTINUE


def _reject_argument(
    invocation: CommandInvocation,
    context: CommandExecutionContext,
) -> bool:
    if not invocation.argument:
        return False
    definition = context.registry.resolve(invocation.normalized_identifier)
    usage = definition.usage[0] if definition is not None else invocation.identifier
    context.controller.show_command_message(
        f"{invocation.identifier} 不接受参数。用法：{usage}"
    )
    return True
