from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from artcode.agent import AgentLoop, AgentRunRequest, NORMAL_AGENT_MODE
from artcode.config import ArtCodeConfig, ThinkingConfig, load_config
from artcode.conversation import ConversationContext
from artcode.errors import ConfigError
from artcode.providers.events import CONTENT_DELTA
from artcode.providers.openai_compatible import OpenAICompatibleProvider
from artcode.tools import AllowedPathPolicy, ToolExecutionContext, create_default_tool_registry


ROOT = Path(__file__).resolve().parents[2]


def live_config() -> ArtCodeConfig:
    try:
        config = load_config(ROOT / "artcode.yaml")
    except ConfigError as exc:
        pytest.skip(f"live DeepSeek config unavailable: {exc.message}")
    if "your-deepseek-api-key" in config.api_key or config.api_key.startswith("<"):
        pytest.skip("artcode.yaml still contains a placeholder API key")
    return config


async def collect_reply(provider: OpenAICompatibleProvider, messages: list[dict[str, str]]) -> str:
    parts: list[str] = []
    async for event in provider.stream_chat(messages):
        if event["type"] == CONTENT_DELTA:
            parts.append(event["text"])
    return "".join(parts)


async def test_live_deepseek_stream_returns_content_delta() -> None:
    config = live_config()
    provider = OpenAICompatibleProvider(config)

    reply = await collect_reply(provider, [{"role": "user", "content": "只回复 OK"}])

    assert reply.strip()


async def test_live_deepseek_multi_turn_context() -> None:
    config = live_config()
    provider = OpenAICompatibleProvider(config)
    context = ConversationContext(system_prompt="你是一个只做简短回答的助手。")
    context.append_user("请记住暗号是 blue42，只回复已记住。")
    first_reply = await collect_reply(provider, context.export_messages())
    context.append_assistant(first_reply)
    context.append_user("刚才的暗号是什么？只回复暗号。")

    second_reply = await collect_reply(provider, context.export_messages())

    assert "blue42" in second_reply.lower()


async def test_live_deepseek_accepts_thinking_mode_payload() -> None:
    config = live_config()
    thinking_config = replace(config, thinking=ThinkingConfig(enabled=True, effort="high"))
    provider = OpenAICompatibleProvider(thinking_config)

    reply = await collect_reply(provider, [{"role": "user", "content": "用一句话回答：1+1 等于几？"}])

    assert reply.strip()


async def test_live_deepseek_agent_loop_reads_file(tmp_path) -> None:
    marker = "LIVE_AGENT_LOOP_MARKER_42"
    allowed_dir = tmp_path / "sandbox"
    allowed_dir.mkdir()
    (allowed_dir / "note.txt").write_text(marker, encoding="utf-8")
    config = live_config()
    config = replace(config, tools=replace(config.tools, allowed_dirs=(allowed_dir.resolve(),)))
    provider = OpenAICompatibleProvider(config)
    context = ConversationContext()
    tool_context = ToolExecutionContext(
        AllowedPathPolicy(config.tools.allowed_dirs),
        default_cwd=config.tools.allowed_dirs[0],
    )
    loop = AgentLoop(
        provider=provider,
        conversation=context,
        tool_registry=create_default_tool_registry(),
        tool_context=tool_context,
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
