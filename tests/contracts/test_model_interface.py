from __future__ import annotations

import json

import httpx
import pytest

from artcode._model import DeepSeekModel
from artcode.core.model import (
    Completed,
    ModelMessage,
    ModelRequest,
    ModelSettings,
    ProtocolMetadata,
    TextDelta,
    ToolDefinition,
    ToolRequest,
    ToolRequests,
    Usage,
)


def settings(*, thinking: bool = False) -> ModelSettings:
    return ModelSettings(
        model="deepseek-chat",
        base_url="https://api.deepseek.example/v1",
        api_key="sk-contract-secret",
        thinking_enabled=thinking,
    )


def sse(*payloads: object) -> bytes:
    lines = [f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode() for payload in payloads]
    return b"".join([*lines, b"data: [DONE]\n\n"])


async def collect(model: DeepSeekModel, request: ModelRequest) -> list[object]:
    return [event async for event in model.stream(request)]


async def test_stream_returns_visible_text_real_usage_and_finish_reason() -> None:
    response = sse(
        {"choices": [{"delta": {"content": "你"}, "finish_reason": None}]},
        {
            "choices": [{"delta": {"content": "好"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
        },
    )
    model = DeepSeekModel(settings(), transport=httpx.MockTransport(lambda _: httpx.Response(200, content=response)))

    events = await collect(model, ModelRequest((ModelMessage("user", "hi"),)))
    await model.close()

    assert events == [TextDelta("你"), TextDelta("好"), Usage(3, 2, 5, None, None), Completed("stop")]


async def test_thinking_is_not_visible_and_tool_metadata_round_trips_opaquely() -> None:
    requests: list[dict[str, object]] = []
    call_number = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_number
        call_number += 1
        requests.append(json.loads(request.content))
        if call_number == 1:
            return httpx.Response(
                200,
                content=sse(
                    {
                        "choices": [{
                            "delta": {
                                "reasoning_content": "PRIVATE-REASONING",
                                "tool_calls": [{
                                    "index": 0,
                                    "id": "call-1",
                                    "function": {"name": "read_file", "arguments": '{"path":"a"}'},
                                }],
                            },
                            "finish_reason": "tool_calls",
                        }]
                    }
                ),
            )
        return httpx.Response(200, content=sse({"choices": [{"delta": {"content": "done"}, "finish_reason": "stop"}]}))

    model = DeepSeekModel(settings(thinking=True), transport=httpx.MockTransport(handler))
    tools = (ToolDefinition("read_file", "read", '{"type":"object"}'),)
    first = await collect(model, ModelRequest((ModelMessage("user", "use tool"),), tools=tools))
    tool_event = next(event for event in first if isinstance(event, ToolRequests))

    assert all(not isinstance(event, TextDelta) or "PRIVATE" not in event.text for event in first)
    assert isinstance(tool_event.metadata, ProtocolMetadata)
    assert "PRIVATE-REASONING" not in repr(tool_event.metadata)
    await collect(
        model,
        ModelRequest(
            (
                ModelMessage("user", "use tool"),
                ModelMessage("assistant", None, tool_requests=tool_event.requests, metadata=tool_event.metadata),
                ModelMessage("tool", "contents", tool_request_id="call-1"),
            ),
            tools=tools,
        ),
    )
    await model.close()

    assistant = requests[1]["messages"][1]
    assert assistant["reasoning_content"] == "PRIVATE-REASONING"
    assert assistant["tool_calls"][0]["id"] == "call-1"


async def test_request_payload_honors_thinking_tools_and_output_limit() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            content=sse({"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]}),
        )

    model = DeepSeekModel(settings(), transport=httpx.MockTransport(handler))
    await collect(
        model,
        ModelRequest(
            (ModelMessage("system", "rules"), ModelMessage("user", "hi")),
            tools=(ToolDefinition("read_file", "read", '{"type":"object","properties":{}}'),),
            max_output_tokens=123,
            thinking_enabled=False,
        ),
    )
    await model.close()

    assert captured["thinking"] == {"type": "disabled"}
    assert captured["tool_choice"] == "auto"
    assert captured["max_tokens"] == 123
    assert captured["stream_options"] == {"include_usage": True}


def test_request_and_message_validation_rejects_ambiguous_protocol_values() -> None:
    with pytest.raises(ValueError):
        ModelMessage("unknown", "x")
    with pytest.raises(ValueError):
        ModelMessage("tool", "x")
    with pytest.raises(ValueError):
        ModelRequest((), max_output_tokens=0)
    with pytest.raises(ValueError):
        ToolDefinition("", "description", "{}")
    with pytest.raises(ValueError):
        ToolRequest("id", "name", "not-json")


async def test_close_is_idempotent_and_stream_after_close_fails() -> None:
    model = DeepSeekModel(settings(), transport=httpx.MockTransport(lambda _: httpx.Response(200)))
    await model.close()
    await model.close()
    with pytest.raises(RuntimeError, match="已关闭"):
        await collect(model, ModelRequest((ModelMessage("user", "x"),)))
