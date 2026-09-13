from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, replace
from typing import Any, Protocol

from artcode.providers.base import ProviderRequest, StreamingProvider
from artcode.providers.events import ContentDelta

from .models import (
    BenchmarkTask,
    JudgeCriterion,
    JudgeResult,
    JudgeStatus,
    VerificationResult,
    WorkspaceChange,
)
from .redaction import Redactor


_EVALUATION = re.compile(r"\A\s*<evaluation>(.*?)</evaluation>\s*\Z", re.DOTALL)


class JudgePort(Protocol):
    async def evaluate(
        self,
        task: BenchmarkTask,
        *,
        final_response: str,
        changes: tuple[WorkspaceChange, ...],
        verifications: tuple[VerificationResult, ...],
    ) -> JudgeResult:
        ...


@dataclass
class LlmJudge:
    provider: StreamingProvider
    redactor: Redactor
    timeout_seconds: float = 60

    async def evaluate(
        self,
        task: BenchmarkTask,
        *,
        final_response: str,
        changes: tuple[WorkspaceChange, ...],
        verifications: tuple[VerificationResult, ...],
    ) -> JudgeResult:
        if task.judge is None:
            return JudgeResult.disabled()
        evidence = {
            "request": self.redactor.preview(task.prompt, limit=4000).text,
            "final_response": self.redactor.preview(final_response, limit=4000).text,
            "changes": [
                {"path": item.path, "kind": item.kind} for item in changes[:200]
            ],
            "verifications": [
                {
                    "id": item.id,
                    "required": item.required,
                    "passed": item.passed,
                    "status": item.status,
                    "evidence": self.redactor.preview(item.evidence, limit=1000).text,
                }
                for item in verifications
            ],
            "rubric": self.redactor.preview(task.judge.rubric, limit=4000).text,
        }
        request = ProviderRequest.from_parts(
            (
                {
                    "role": "system",
                    "content": (
                        "你是独立 Coding Agent 评测员。不得调用工具，不得推翻确定性验证。"
                        "只输出一个 <evaluation>JSON</evaluation> 块。JSON 必须包含整数 score(0-100)、"
                        "criteria(1-10项，每项含 name、整数 score、reason) 与 summary。"
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(evidence, ensure_ascii=False, sort_keys=True),
                },
            ),
            tools=None,
            max_output_tokens=1200,
            thinking_enabled=False,
        )
        chunks: list[str] = []
        try:
            async with asyncio.timeout(self.timeout_seconds):
                async for event in self.provider.stream(request):
                    if isinstance(event, ContentDelta):
                        chunks.append(event.text)
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            return JudgeResult.unavailable("Judge 请求超时")
        except Exception as exc:
            return JudgeResult.unavailable(
                self.redactor.preview(str(exc), limit=1000).text or "Judge Provider 失败"
            )
        result = parse_judge_response("".join(chunks), self.redactor)
        if result.status == JudgeStatus.AVAILABLE and result.score is not None:
            return replace(
                result,
                minimum_score=task.judge.minimum_score,
                meets_minimum=result.score >= task.judge.minimum_score,
            )
        return result


def parse_judge_response(raw: str, redactor: Redactor | None = None) -> JudgeResult:
    scrubber = redactor or Redactor()
    match = _EVALUATION.fullmatch(raw)
    if match is None:
        return JudgeResult.unavailable("Judge 响应必须只含一个 evaluation 块")
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError:
        return JudgeResult.unavailable("Judge evaluation 不是合法 JSON")
    if not isinstance(payload, dict) or set(payload) != {"score", "criteria", "summary"}:
        return JudgeResult.unavailable("Judge evaluation 字段不完整或含未知字段")
    score = payload.get("score")
    summary = payload.get("summary")
    criteria = payload.get("criteria")
    if isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= 100:
        return JudgeResult.unavailable("Judge score 必须是 0～100 的整数")
    if not isinstance(summary, str) or not summary.strip():
        return JudgeResult.unavailable("Judge summary 必须是非空字符串")
    if not isinstance(criteria, list) or not 1 <= len(criteria) <= 10:
        return JudgeResult.unavailable("Judge criteria 必须包含 1～10 项")
    parsed: list[JudgeCriterion] = []
    for index, item in enumerate(criteria):
        if not isinstance(item, dict) or set(item) != {"name", "score", "reason"}:
            return JudgeResult.unavailable(f"Judge criterion[{index}] 字段非法")
        item_score = item.get("score")
        if (
            not isinstance(item.get("name"), str)
            or not item["name"].strip()
            or isinstance(item_score, bool)
            or not isinstance(item_score, int)
            or not 0 <= item_score <= 100
            or not isinstance(item.get("reason"), str)
            or not item["reason"].strip()
        ):
            return JudgeResult.unavailable(f"Judge criterion[{index}] 值非法")
        parsed.append(
            JudgeCriterion(
                scrubber.preview(item["name"], limit=200).text,
                item_score,
                scrubber.preview(item["reason"], limit=1000).text,
            )
        )
    return JudgeResult(
        JudgeStatus.AVAILABLE,
        score=score,
        criteria=tuple(parsed),
        summary=scrubber.preview(summary, limit=2000).text,
    )


__all__ = ["JudgePort", "LlmJudge", "parse_judge_response"]
