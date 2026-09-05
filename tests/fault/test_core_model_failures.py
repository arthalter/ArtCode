from __future__ import annotations

import asyncio

import httpx
import pytest

from artcode._model import DeepSeekModel
from artcode.core.model import (
    AuthenticationFailure,
    ContextWindowFailure,
    ModelMessage,
    ModelRequest,
    ModelSettings,
    NetworkFailure,
    ProtocolFailure,
    TimeoutFailure,
)


def settings() -> ModelSettings:
    return ModelSettings("deepseek-chat", "https://example.invalid", "sk-never-leak")


async def consume(model: DeepSeekModel) -> None:
    async for _ in model.stream(ModelRequest((ModelMessage("user", "x"),))):
        pass


@pytest.mark.parametrize(
    ("external", "failure"),
    [
        (httpx.ConnectError("offline"), NetworkFailure),
        (httpx.ReadTimeout("slow"), TimeoutFailure),
        (httpx.RemoteProtocolError("broken"), ProtocolFailure),
        (httpx.DecodingError("bad bytes"), ProtocolFailure),
    ],
)
async def test_transport_failure_is_mapped_without_retry(external: Exception, failure: type[Exception]) -> None:
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise external

    model = DeepSeekModel(settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(failure):
        await consume(model)
    await model.close()
    assert attempts == 1


@pytest.mark.parametrize(
    ("status", "body", "failure"),
    [
        (401, "bad sk-never-leak", AuthenticationFailure),
        (400, "context_length_exceeded sk-never-leak", ContextWindowFailure),
        (500, "server leaked sk-never-leak", ProtocolFailure),
    ],
)
async def test_http_failures_are_distinct_and_secret_safe(status: int, body: str, failure: type[Exception]) -> None:
    model = DeepSeekModel(settings(), transport=httpx.MockTransport(lambda _: httpx.Response(status, text=body)))
    with pytest.raises(failure) as caught:
        await consume(model)
    await model.close()
    assert "sk-never-leak" not in str(caught.value)


class BrokenStream(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield b'data: {"choices":[{"delta":{"content":"partial"},"finish_reason":null}]}\n\n'
        raise httpx.ReadError("dropped")

    async def aclose(self) -> None:
        return None


async def test_partial_stream_failure_does_not_retry_or_emit_completion() -> None:
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(200, stream=BrokenStream())

    model = DeepSeekModel(settings(), transport=httpx.MockTransport(handler))
    stream = model.stream(ModelRequest((ModelMessage("user", "x"),)))
    first = await anext(stream)
    assert first.text == "partial"
    with pytest.raises(ProtocolFailure):
        await anext(stream)
    await model.close()
    assert attempts == 1


async def test_done_without_text_or_tool_request_is_protocol_failure() -> None:
    model = DeepSeekModel(
        settings(),
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, content=b"data: [DONE]\n\n")
        ),
    )
    with pytest.raises(ProtocolFailure, match="空响应"):
        await consume(model)
    await model.close()


async def test_cancellation_is_never_remapped() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise asyncio.CancelledError

    model = DeepSeekModel(settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(asyncio.CancelledError):
        await consume(model)
    await model.close()
