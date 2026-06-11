from __future__ import annotations

import asyncio
import json
import signal
from dataclasses import dataclass, field
from typing import Any, Protocol

from artcode.commands import CommandRegistry, create_default_registry
from artcode.config import ArtCodeConfig
from artcode.conversation import ConversationContext
from artcode.errors import RequestError
from artcode.providers.base import StreamingProvider
from artcode.providers.events import CONTENT_DELTA, DONE, TOOL_CALLS
from artcode.providers.tool_calls import ToolCall
from artcode.tools import (
    AllowedPathPolicy,
    PreparedToolCall,
    ToolExecutionContext,
    ToolPreview,
    ToolRegistry,
    ToolResult,
    create_default_tool_registry,
    denied_result,
    error_result,
)
from artcode.tui import UserRequestedExit


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


@dataclass(frozen=True)
class GenerationResult:
    text: str
    tool_calls: list[ToolCall]


@dataclass
class ArtCodeRuntime:
    config: ArtCodeConfig
    provider: StreamingProvider
    conversation: ConversationContext
    tui: TuiApp
    tool_registry: ToolRegistry | None = None
    tool_context: ToolExecutionContext | None = None
    commands: CommandRegistry = field(default_factory=create_default_registry)

    def __post_init__(self) -> None:
        if self.tool_registry is None:
            self.tool_registry = create_default_tool_registry()
        if self.tool_context is None:
            policy = AllowedPathPolicy(self.config.tools.allowed_dirs)
            self.tool_context = ToolExecutionContext(policy, default_cwd=self.config.tools.allowed_dirs[0])

    async def run(self) -> int:
        self.tui.show_startup(self.config.safe_status())
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
                if command_result.message:
                    self.tui.show_help(command_result.message)
                if command_result.should_exit:
                    self.tui.show_exit()
                    return 0
                continue

            self.tui.show_user_label()
            self.conversation.append_user(user_input)
            self.tui.show_assistant_label()

            result = await self._generate_model_response(allow_tools=True)
            if result is None:
                self.tui.show_cancelled()
                continue
            if result.tool_calls:
                await self._handle_tool_calls(result.tool_calls)
            elif result.text:
                self.conversation.append_assistant(result.text)

    async def _generate_model_response(self, allow_tools: bool) -> GenerationResult | None:
        messages = self.conversation.export_messages()
        tools = self.tool_registry.openai_tools() if allow_tools and self.tool_registry is not None else None
        task = asyncio.create_task(self._consume_provider_stream(messages, tools))
        self._install_generation_cancel_handler(task)
        try:
            return await task
        except asyncio.CancelledError:
            return None
        except RequestError as exc:
            self.tui.show_error(exc)
            return GenerationResult("", [])
        finally:
            self._remove_generation_cancel_handler()

    async def _consume_provider_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> GenerationResult:
        parts: list[str] = []
        tool_calls: list[ToolCall] = []
        async for event in self.provider.stream_chat(messages, tools=tools):
            event_type = event.get("type")
            if event_type == CONTENT_DELTA:
                text = event.get("text", "")
                parts.append(text)
                self.tui.stream_delta(text)
            elif event_type == TOOL_CALLS:
                tool_calls = event.get("tool_calls", [])
            elif event_type == DONE:
                self.tui.finish_assistant_message()
                return GenerationResult("".join(parts), tool_calls)
        return GenerationResult("".join(parts), tool_calls)

    async def _handle_tool_calls(self, tool_calls: list[ToolCall]) -> None:
        self.conversation.append_assistant_tool_call(tool_calls)
        if len(tool_calls) > 1:
            for tool_call in tool_calls:
                result = error_result(
                    tool_call.name or "unknown_tool",
                    "too_many_tool_calls",
                    "ch03 同一轮只允许一个工具调用，本轮没有执行任何工具。",
                )
                self.conversation.append_tool_result(tool_call, result)
                self.tui.show_tool_result_summary(result)
            await self._summarize_tool_result()
            return

        tool_call = tool_calls[0]
        result = await self._execute_one_tool_call(tool_call)
        self.conversation.append_tool_result(tool_call, result)
        self.tui.show_tool_result_summary(result)
        await self._summarize_tool_result()

    async def _execute_one_tool_call(self, tool_call: ToolCall) -> ToolResult:
        arguments_result = self._parse_tool_arguments(tool_call)
        if isinstance(arguments_result, ToolResult):
            return arguments_result
        arguments = arguments_result

        tool = self.tool_registry.get(tool_call.name) if self.tool_registry is not None else None
        if tool is None:
            return error_result(tool_call.name or "unknown_tool", "tool_not_found", f"未知工具：{tool_call.name}")

        prepared = tool.prepare(arguments, self.tool_context)
        if isinstance(prepared, ToolResult):
            return prepared

        self.tui.show_tool_preview(prepared.preview)
        if prepared.preview.requires_confirmation:
            confirmed = await self.tui.confirm_tool_execution(prepared.preview)
            if not confirmed:
                return denied_result(tool.name)

        return await tool.execute(prepared, self.tool_context)

    def _parse_tool_arguments(self, tool_call: ToolCall) -> dict[str, Any] | ToolResult:
        try:
            parsed = json.loads(tool_call.arguments_json or "{}")
        except json.JSONDecodeError as exc:
            return error_result(tool_call.name or "unknown_tool", "invalid_arguments", f"工具参数不是合法 JSON：{exc}")
        if not isinstance(parsed, dict):
            return error_result(tool_call.name or "unknown_tool", "invalid_arguments", "工具参数 JSON 必须是对象。")
        return parsed

    async def _summarize_tool_result(self) -> None:
        self.tui.show_assistant_label()
        result = await self._generate_model_response(allow_tools=False)
        if result is None:
            self.tui.show_cancelled()
            return
        if result.text:
            self.conversation.append_assistant(result.text)

    def _install_generation_cancel_handler(self, task: asyncio.Task[str]) -> None:
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
