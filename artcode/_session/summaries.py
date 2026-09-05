from __future__ import annotations

import json

from artcode.core.model import Completed, Model, ModelMessage, ModelRequest, TextDelta, ToolRequests
from artcode.core.session import AssistantFact, ToolExchangeFact, TranscriptFact


async def generate_summary(
    model: Model,
    facts: tuple[TranscriptFact, ...],
    *,
    start: int,
    end: int,
    previous_summary: str | None = None,
) -> str:
    material: list[dict[str, object]] = []
    if previous_summary:
        material.append({"kind": "previous_summary", "text": previous_summary[:8_000]})
    for fact in facts[start:end]:
        if isinstance(fact, AssistantFact):
            material.append({"kind": "assistant", "text": fact.text[:4_000]})
        elif isinstance(fact, ToolExchangeFact):
            material.append(
                {
                    "kind": "tool_exchange",
                    "tools": [item.name for item in fact.requests],
                    "results": [item.content[:4_000] for item in fact.results],
                }
            )
    if not material or (len(material) == 1 and previous_summary):
        return ""
    request = ModelRequest(
        (
            ModelMessage(
                "system",
                "Summarize only the supplied historical assistant/tool data. "
                "Do not call tools, invent facts, or include provider metadata.",
            ),
            ModelMessage("user", json.dumps(material, ensure_ascii=False)),
        ),
        max_output_tokens=4_000,
        thinking_enabled=False,
    )
    parts: list[str] = []
    completed = False
    async for event in model.stream(request):
        if isinstance(event, TextDelta):
            parts.append(event.text)
        elif isinstance(event, ToolRequests):
            raise ValueError("Summary 响应不得请求 Tool。")
        elif isinstance(event, Completed):
            completed = True
    summary = "".join(parts).strip()
    if not completed or not summary:
        raise ValueError("Summary 响应没有完整文本。")
    return summary
