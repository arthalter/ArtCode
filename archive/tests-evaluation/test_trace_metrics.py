from __future__ import annotations

import json
from pathlib import Path

from artcode.agent.events import (
    context_status_event,
    model_turn_completed_event,
    stopped_event,
    text_delta_event,
    token_usage_event,
    tool_result_event,
    StopReason,
)
from artcode.evaluation.metrics import build_attempt_metrics, trace_metric_values
from artcode.evaluation.models import JudgeResult, VerificationResult
from artcode.evaluation.redaction import Redactor
from artcode.evaluation.trace import RunTraceRecorder, load_trace
from artcode.providers.events import TokenUsage
from artcode.providers.tool_calls import ToolCall
from artcode.tools.results import error_result, success_result


def test_trace_normalizes_events_and_sequence(tmp_path: Path) -> None:
    recorder = RunTraceRecorder(
        tmp_path / "trace.jsonl",
        run_id="run",
        task_id="task",
        attempt=1,
        redactor=Redactor(["secret"]),
    )
    recorder.start()
    for _ in range(100):
        recorder.record_agent_event(text_delta_event("x"))
    recorder.record_agent_event(model_turn_completed_event("secret" + "a" * 5000, 1))
    recorder.record_agent_event(
        tool_result_event(
            ToolCall("call-1", "read_file", '{"path":"a.txt"}'),
            success_result("read_file", "ok", "content"),
        )
    )
    recorder.record_agent_event(token_usage_event(TokenUsage(10, 5, 15)))
    recorder.record_agent_event(context_status_event("lightweight", "success", 100, 40, 1, False))
    recorder.record_agent_event(stopped_event(StopReason.NATURAL))
    recorder.finish({"status": "passed"})
    records = load_trace(recorder.path)
    assert [item.sequence for item in records] == list(range(1, len(records) + 1))
    assert not any(item.kind == "text_delta" for item in records)
    model = next(item for item in records if item.kind == "model_turn_completed")
    assert len(model.payload["text_preview"]) <= 4013
    assert "secret" not in recorder.path.read_text(encoding="utf-8")


def test_metrics_count_repeats_permissions_context_and_usage(tmp_path: Path) -> None:
    recorder = RunTraceRecorder(
        tmp_path / "trace.jsonl",
        run_id="run",
        task_id="task",
        attempt=1,
        redactor=Redactor(),
    )
    recorder.start()
    call = ToolCall("a", "run_command", '{"command":"x"}')
    recorder.record_agent_event(tool_result_event(call, error_result("run_command", "permission_denied", "no")))
    recorder.record_agent_event(tool_result_event(ToolCall("b", call.name, call.arguments_json), error_result("run_command", "permission_required", "no")))
    recorder.record_agent_event(tool_result_event(ToolCall("c", call.name, '{"command":"y"}'), error_result("run_command", "process_error", "bad")))
    recorder.record_agent_event(context_status_event("auto", "success", 120000, 45000, 0, False))
    recorder.record_agent_event(token_usage_event(TokenUsage(600, 400, 1000)))
    recorder.record_agent_event(token_usage_event(TokenUsage(900, 600, 1500)))
    recorder.finish({"status": "failed"})
    values = trace_metric_values(recorder.records)
    assert values["tool_calls"] == 3
    assert values["repeated_tool_calls"] == 1
    assert values["permission_denials"] == 2
    assert values["permission_overhead_proxy"] == 5
    assert values["context_tokens_saved"] == 75000
    assert values["context_savings_rate"] == 0.625
    assert values["total_tokens"] == 2500


def test_missing_usage_and_context_are_null() -> None:
    metrics = build_attempt_metrics(
        [],
        [VerificationResult("v", "file_exists", True, True, "passed", 1)],
        passed=True,
        judge=JudgeResult.disabled(),
    )
    assert metrics.total_tokens.value is None
    assert metrics.context_before_tokens.value is None
    assert metrics.verifier_pass_rate.value == 1.0
    assert metrics.permission_confirmations.value is None
    assert metrics.permission_confirmations.source == "unavailable"
