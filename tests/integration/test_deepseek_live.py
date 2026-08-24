from __future__ import annotations

from dataclasses import replace
import pytest

pytestmark = pytest.mark.live

from artcode.agent import AgentLoop, AgentRunRequest, NORMAL_AGENT_MODE, RequestPreparer
from artcode.config import ArtCodeConfig, ThinkingConfig
from tests.live.conftest import load_live_config
from artcode.conversation import ConversationContext
from artcode.permissions import PermissionState
from artcode.permissions.service import PermissionService
from artcode.prompting.assembler import PromptRequestAssembler
from artcode.providers import DeepSeekChatProvider, ProviderRequest
from artcode.providers.events import ContentDelta
from artcode.tools import ToolEnvironment, create_default_tool_registry
from artcode.tools.execution import ToolExecutionService


def live_config() -> ArtCodeConfig:
    return load_live_config()


async def collect_reply(provider: DeepSeekChatProvider, messages: list[dict[str, str]]) -> str:
    parts: list[str] = []
    async for event in provider.stream(ProviderRequest.from_parts(messages)):
        if isinstance(event, ContentDelta):
            parts.append(event.text)
    return "".join(parts)


async def test_live_deepseek_stream_returns_content_delta() -> None:
    config = live_config()
    provider = DeepSeekChatProvider(config)

    reply = await collect_reply(provider, [{"role": "user", "content": "只回复 OK"}])

    assert reply.strip()


async def test_live_deepseek_multi_turn_context() -> None:
    config = live_config()
    provider = DeepSeekChatProvider(config)
    context = ConversationContext(system_prompt="你是一个只做简短回答的助手。")
    context.append_user("请记住暗号是 blue42，只回复已记住。")
    first_reply = await collect_reply(provider, context.export_messages())
    context.append_assistant(first_reply)
    context.append_user("刚才的暗号是什么？只回复暗号。")

    second_reply = await collect_reply(provider, context.export_messages())

    assert "blue42" in second_reply.lower()


async def test_live_deepseek_accepts_thinking_mode_payload() -> None:
    config = live_config()
    thinking_config = replace(config, thinking=ThinkingConfig(enabled=True))
    provider = DeepSeekChatProvider(thinking_config)

    reply = await collect_reply(provider, [{"role": "user", "content": "用一句话回答：1+1 等于几？"}])

    assert reply.strip()


async def test_live_deepseek_agent_loop_reads_file(tmp_path) -> None:
    marker = "LIVE_AGENT_LOOP_MARKER_42"
    allowed_dir = tmp_path / "sandbox"
    allowed_dir.mkdir()
    (allowed_dir / "note.txt").write_text(marker, encoding="utf-8")
    config = live_config()
    config = replace(config)
    provider = DeepSeekChatProvider(config)
    context = ConversationContext()
    environment = ToolEnvironment.from_workspace(allowed_dir)
    permission_state = PermissionState()
    registry = create_default_tool_registry()
    loop = AgentLoop(
        provider=provider,
        conversation=context,
        tool_registry=registry,
        tool_environment=environment,
        tool_executor=ToolExecutionService(
            registry,
            environment,
            PermissionService(permission_state),
        ),
        request_preparer=RequestPreparer(
            context,
            PromptRequestAssembler(),
            registry,
            environment,
            permission_state,
        ),
    )

    events = [
        event
        async for event in loop.run(
            AgentRunRequest(
                "请调用 read_file 工具读取 note.txt，然后只回复文件内容。不要猜测，必须使用工具。",
                NORMAL_AGENT_MODE,
                max_iterations=4,
            )
        )
    ]

    messages = context.export_messages()
    assert any(message.get("role") == "tool" and message.get("name") == "read_file" for message in messages)
    assert marker in messages[-1]["content"]
    assert events[-1].payload["reason"] == "natural"
