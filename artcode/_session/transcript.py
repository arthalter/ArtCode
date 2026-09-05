from __future__ import annotations

import base64
from typing import Any

from artcode.core.model import ProtocolMetadata, ToolRequest
from artcode.core.session import (
    AssistantCompletion,
    AssistantFact,
    SessionCorrupt,
    ToolExchangeFact,
    TranscriptFact,
    UserFact,
)
from artcode.core.tool import ToolResult


def fact_payload(fact: TranscriptFact) -> dict[str, Any]:
    if isinstance(fact, UserFact):
        return {"kind": "user", "text": fact.text}
    if isinstance(fact, AssistantFact):
        return {
            "kind": "assistant",
            "text": fact.text,
            "completion": fact.completion.value,
        }
    return {
        "kind": "tool_exchange",
        "requests": [
            {"id": item.id, "name": item.name, "arguments_json": item.arguments_json}
            for item in fact.requests
        ],
        "results": [
            {
                "call_id": item.call_id,
                "tool_name": item.tool_name,
                "ok": item.ok,
                "content": item.content,
                "error_code": item.error_code,
            }
            for item in fact.results
        ],
        "metadata": (
            base64.b64encode(fact.metadata.envelope).decode("ascii")
            if fact.metadata is not None
            else None
        ),
        "assistant_text": fact.assistant_text,
    }


def fact_from_payload(payload: dict[str, Any]) -> TranscriptFact:
    kind = payload.get("kind")
    if kind == "user" and set(payload) == {"kind", "text"} and isinstance(payload["text"], str):
        return UserFact(payload["text"])
    if kind == "assistant" and set(payload) == {"kind", "text", "completion"} and isinstance(payload["text"], str):
        try:
            completion = AssistantCompletion(payload["completion"])
        except (TypeError, ValueError) as exc:
            raise ValueError("Assistant 记录 completion 无效。") from exc
        return AssistantFact(payload["text"], completion)
    if kind == "tool_exchange":
        try:
            requests_raw = payload["requests"]
            results_raw = payload["results"]
            metadata_raw = payload["metadata"]
            assistant_text = payload["assistant_text"]
            if set(payload) != {"kind", "requests", "results", "metadata", "assistant_text"}:
                raise ValueError("字段不符")
            if not isinstance(assistant_text, str):
                raise ValueError("assistant_text 不是字符串")
            if not isinstance(requests_raw, list) or not isinstance(results_raw, list):
                raise ValueError("请求或结果不是列表")
            requests = tuple(
                ToolRequest(item["id"], item["name"], item["arguments_json"])
                for item in requests_raw
                if isinstance(item, dict)
                and set(item) == {"id", "name", "arguments_json"}
            )
            results = tuple(
                ToolResult(
                    item["call_id"],
                    item["tool_name"],
                    item["ok"],
                    item["content"],
                    item["error_code"],
                )
                for item in results_raw
                if isinstance(item, dict)
                and set(item) == {"call_id", "tool_name", "ok", "content", "error_code"}
            )
            if len(requests) != len(requests_raw) or len(results) != len(results_raw):
                raise ValueError("请求或结果结构无效")
            if not requests or len(requests) != len(results):
                raise ValueError("请求与结果不完整")
            if [item.id for item in requests] != [item.call_id for item in results]:
                raise ValueError("请求与结果 ID 不匹配")
            metadata = None
            if metadata_raw is not None:
                if not isinstance(metadata_raw, str):
                    raise ValueError("metadata 不是字符串")
                metadata = ProtocolMetadata(base64.b64decode(metadata_raw, validate=True))
            return ToolExchangeFact(requests, results, metadata, assistant_text)
        except (KeyError, TypeError, ValueError) as exc:
            raise SessionCorrupt(f"Tool exchange 记录不完整：{exc}") from exc
    raise ValueError("Transcript 记录 kind 或字段无效。")


def complete_exchange(
    requests: tuple[ToolRequest, ...],
    results: tuple[ToolResult, ...],
    *,
    metadata: ProtocolMetadata | None,
    cancelled: bool,
    assistant_text: str = "",
) -> ToolExchangeFact:
    if not requests or not all(isinstance(item, ToolRequest) for item in requests):
        raise ValueError("Tool exchange 必须包含请求。")
    if len({item.id for item in requests}) != len(requests):
        raise ValueError("Tool request ID 必须唯一。")
    by_id: dict[str, ToolResult] = {}
    for result in results:
        if not isinstance(result, ToolResult) or result.call_id in by_id:
            raise ValueError("Tool Result 必须合法且 ID 唯一。")
        by_id[result.call_id] = result
    request_ids = {item.id for item in requests}
    if set(by_id) - request_ids:
        raise ValueError("Tool Result 与请求 ID 不匹配。")
    if not cancelled and set(by_id) != request_ids:
        raise ValueError("Tool exchange 必须包含完整结果。")
    ordered: list[ToolResult] = []
    for request in requests:
        result = by_id.get(request.id)
        if result is None:
            result = ToolResult(
                request.id,
                request.name,
                False,
                "工具调用因 Run 取消而未完成。",
                "cancelled",
            )
        if result.tool_name != request.name:
            raise ValueError("Tool Result 名称必须与请求匹配。")
        ordered.append(result)
    if not isinstance(assistant_text, str):
        raise TypeError("assistant_text 必须是字符串。")
    return ToolExchangeFact(requests, tuple(ordered), metadata, assistant_text)
