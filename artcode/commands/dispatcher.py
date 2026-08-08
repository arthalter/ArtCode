from __future__ import annotations

from .base import (
    CommandController,
    CommandExecutionContext,
    CommandFlow,
    CommandInvocation,
)
from .registry import CommandRegistry


class CommandDispatcher:
    def __init__(self, registry: CommandRegistry) -> None:
        self.registry = registry

    async def dispatch(
        self,
        invocation: CommandInvocation,
        controller: CommandController,
    ) -> CommandFlow:
        definition = self.registry.resolve(invocation.normalized_identifier)
        if definition is None:
            controller.show_command_message(
                f"未知命令：{invocation.identifier}。请使用 /help 查看可用命令。"
            )
            return CommandFlow.CONTINUE
        context = CommandExecutionContext(self.registry, controller)
        return await definition.handler(invocation, context)
