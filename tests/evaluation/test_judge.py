from __future__ import annotations

import json

import pytest

from artcode.evaluation.judge import LlmJudge, parse_judge_response
from artcode.evaluation.manifest import load_benchmark
from artcode.evaluation.models import JudgeStatus
from artcode.evaluation.redaction import Redactor
from artcode.providers.events import ContentDelta, StreamCompleted


def _response(score: object = 88, criteria: object | None = None) -> str:
    value = {
        "score": score,
        "criteria": criteria
        if criteria is not None
        else [{"name": "正确性", "score": 90, "reason": "验证一致"}],
        "summary": "完成良好",
    }
    return f"<evaluation>{json.dumps(value, ensure_ascii=False)}</evaluation>"


def test_parse_valid_judge_response() -> None:
    result = parse_judge_response(_response())
    assert result.status == JudgeStatus.AVAILABLE
    assert result.score == 88


@pytest.mark.parametrize(
    "raw",
    [
        "prefix " + _response(),
        _response(-1),
        _response(101),
        _response(1.5),
        _response(criteria=[]),
        "<evaluation>not-json</evaluation>",
        _response() + _response(),
    ],
)
def test_invalid_judge_response_is_unavailable(raw: str) -> None:
    assert parse_judge_response(raw).status == JudgeStatus.UNAVAILABLE


class _CapturingProvider:
    def __init__(self, text: str) -> None:
        self.text = text
        self.request = None

    async def stream(self, request):
        self.request = request
        yield ContentDelta(self.text)
        yield StreamCompleted("stop")


@pytest.mark.asyncio
async def test_judge_request_has_no_tools_and_thinking_off(benchmark_file) -> None:
    raw = benchmark_file.read_text(encoding="utf-8")
    raw = raw.replace(
        "    verifiers:",
        "    judge:\n      rubric: explain result\n      minimum_score: 70\n    verifiers:",
    )
    benchmark_file.write_text(raw, encoding="utf-8")
    task = load_benchmark(benchmark_file).tasks[0]
    provider = _CapturingProvider(_response())
    result = await LlmJudge(provider, Redactor()).evaluate(
        task,
        final_response="done",
        changes=(),
        verifications=(),
    )
    assert result.status == JudgeStatus.AVAILABLE
    assert result.minimum_score == 70
    assert result.meets_minimum is True
    assert provider.request.tools is None
    assert provider.request.thinking_enabled is False
