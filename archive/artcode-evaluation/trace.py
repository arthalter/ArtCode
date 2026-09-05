from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from artcode.agent.events import AgentEvent, AgentEventType
from artcode.providers.tool_calls import ToolCall
from artcode.tools.results import ToolResult

from .models import TraceRecord, to_jsonable
from .redaction import Redactor, canonical_json, sha256_text


class RunTraceRecorder:
    def __init__(
        self,
        path: Path,
        *,
        run_id: str,
        task_id: str,
        attempt: int,
        redactor: Redactor,
    ) -> None:
        self.path = path
        self.run_id = run_id
        self.task_id = task_id
        self.attempt = attempt
        self.redactor = redactor
        self._started = time.monotonic()
        self._sequence = 0
        self._handle = None
        self.records: list[TraceRecord] = []

    def start(self, payload: dict[str, Any] | None = None) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("x", encoding="utf-8")
        self.append("attempt_started", payload or {})

    def record_agent_event(self, event: AgentEvent) -> None:
        if event.type == AgentEventType.TEXT_DELTA:
            return
        payload = self._normalize_event(event)
        self.append(event.type.value, payload)

    def finish(self, payload: dict[str, Any]) -> None:
        if self._handle is None:
            return
        self.append("attempt_finished", payload)
        self._handle.flush()
        os.fsync(self._handle.fileno())
        self._handle.close()
        self._handle = None

    def close_partial(self) -> None:
        if self._handle is None:
            return
        self._handle.flush()
        os.fsync(self._handle.fileno())
        self._handle.close()
        self._handle = None

    def append(self, kind: str, payload: dict[str, Any]) -> TraceRecord:
        if self._handle is None:
            raise RuntimeError("Trace 尚未启动")
        self._sequence += 1
        record = TraceRecord(
            schema_version=1,
            run_id=self.run_id,
            task_id=self.task_id,
            attempt=self.attempt,
            sequence=self._sequence,
            elapsed_ms=max(0, int((time.monotonic() - self._started) * 1000)),
            kind=kind,
            payload=self.redactor.redact_value(payload),
        )
        self.records.append(record)
        self._handle.write(
            json.dumps(to_jsonable(record), ensure_ascii=False, sort_keys=True) + "\n"
        )
        self._handle.flush()
        return record

    def _normalize_event(self, event: AgentEvent) -> dict[str, Any]:
        payload = event.payload
        if event.type == AgentEventType.MODEL_TURN_COMPLETED:
            preview = self.redactor.preview(str(payload.get("text", "")), limit=4000)
            return {
                "text_preview": preview.text,
                "text_sha256": preview.sha256,
                "text_chars": preview.original_chars,
                "text_truncated": preview.truncated,
                "tool_call_count": _safe_int(payload.get("tool_call_count")),
            }
        if event.type == AgentEventType.MODEL_REQUEST:
            return {
                "tool_count": _safe_int(payload.get("tool_count")),
                "tool_definition_bytes": _safe_int(
                    payload.get("tool_definition_bytes")
                ),
                "tool_definition_tokens": _safe_int(
                    payload.get("tool_definition_tokens")
                ),
                "tokenizer": str(payload.get("tokenizer", "")),
                "tool_payload_sha256": str(payload.get("tool_payload_sha256", "")),
            }
        if event.type == AgentEventType.PERMISSION_AUDIT:
            allowed = {
                "event",
                "tool_name",
                "target_sha256",
                "target_chars",
                "action",
                "source",
                "choice",
                "rule_index",
                "rule_file_sha256",
                "persistent_rule_hit",
                "ok",
                "error_type",
                "mcp",
            }
            return {
                str(key): value
                for key, value in payload.items()
                if key in allowed
                and isinstance(value, (str, int, bool, type(None)))
            }
        if event.type == AgentEventType.TOOL_RESULT:
            tool_call = payload.get("tool_call")
            result = payload.get("result")
            if isinstance(tool_call, ToolCall) and isinstance(result, ToolResult):
                arguments = _canonical_arguments(tool_call.arguments_json)
                args_preview = self.redactor.preview(arguments, limit=2000)
                evidence = result.message
                if result.content:
                    evidence += "\n" + result.content
                output_preview = self.redactor.preview(evidence, limit=4000)
                return {
                    "tool_call_id": tool_call.id,
                    "tool_name": tool_call.name,
                    "arguments_preview": args_preview.text,
                    "arguments_sha256": args_preview.sha256,
                    "arguments_chars": args_preview.original_chars,
                    "arguments_truncated": args_preview.truncated,
                    "ok": result.ok,
                    "status": result.status,
                    "error_code": result.error_code,
                    "bytes_returned": result.bytes_returned,
                    "output_preview": output_preview.text,
                    "output_sha256": output_preview.sha256,
                    "output_chars": output_preview.original_chars,
                    "output_truncated": output_preview.truncated,
                }
        if event.type == AgentEventType.CONTEXT_STATUS:
            return {
                "trigger": str(payload.get("trigger", "")),
                "status": str(payload.get("status", "")),
                "before_tokens": _safe_int(payload.get("before_tokens")),
                "after_tokens": _safe_int(payload.get("after_tokens")),
                "persisted_count": _safe_int(payload.get("persisted_count")),
                "circuit_open": bool(payload.get("circuit_open", False)),
                "message": self.redactor.preview(str(payload.get("message", "")), limit=1000).text,
            }
        if event.type == AgentEventType.TOKEN_USAGE:
            return {
                name: _safe_int(payload.get(name))
                for name in (
                    "prompt_tokens",
                    "completion_tokens",
                    "total_tokens",
                    "cached_tokens",
                    "cache_miss_tokens",
                )
            }
        return self.redactor.redact_value(_bounded_payload(payload, self.redactor))


def load_trace(path: Path) -> tuple[TraceRecord, ...]:
    records: list[TraceRecord] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            try:
                raw = json.loads(line)
                records.append(TraceRecord(**raw))
            except (json.JSONDecodeError, TypeError) as exc:
                raise ValueError(f"Trace 第 {line_number} 行无效：{exc}") from exc
    return tuple(records)


def _canonical_arguments(raw: str) -> str:
    try:
        return canonical_json(json.loads(raw))
    except json.JSONDecodeError:
        return raw


def _bounded_payload(payload: dict[str, Any], redactor: Redactor) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in payload.items():
        if isinstance(value, str):
            result[str(key)] = redactor.preview(value, limit=1000).text
        elif isinstance(value, (int, float, bool)) or value is None:
            result[str(key)] = value
        else:
            preview = redactor.preview_json(value, limit=1000)
            result[str(key)] = preview.text
            result[f"{key}_sha256"] = sha256_text(canonical_json(value))
    return result


def _safe_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


__all__ = ["RunTraceRecorder", "load_trace"]
