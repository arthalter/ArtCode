from __future__ import annotations

import json

import httpx

from artcode._model import DeepSeekModel
from artcode.core.model import Completed, ModelMessage, ModelRequest, ModelSettings, TextDelta, Usage


async def test_model_stream_is_one_request_with_ordered_domain_events() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        assert request.url == "https://model.example/v1/chat/completions"
        content = (
            b'data: {"choices":[{"delta":{"reasoning_content":"hidden"},"finish_reason":null}]}\n\n'
            b'data: {"choices":[{"delta":{"content":"answer"},"finish_reason":"length"}]}\n\n'
            b'data: {"choices":[],"usage":{"total_tokens":9}}\n\n'
            b'data: [DONE]\n\n'
        )
        return httpx.Response(200, content=content)

    model = DeepSeekModel(
        ModelSettings("deepseek-chat", "https://model.example/v1", "secret"),
        transport=httpx.MockTransport(handler),
    )
    events = [event async for event in model.stream(ModelRequest((ModelMessage("user", "question"),)))]
    await model.close()

    assert events == [TextDelta("answer"), Usage(None, None, 9, None, None), Completed("length")]
    assert attempts == 1
