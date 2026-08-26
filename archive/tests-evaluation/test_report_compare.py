from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from artcode.evaluation.compare import ReportComparisonError, compare_reports, load_report
from artcode.evaluation.manifest import load_benchmark
from artcode.evaluation.models import (
    AttemptMetrics,
    AttemptResult,
    AttemptStatus,
    JudgeResult,
    MetricValue,
)
from artcode.evaluation.redaction import Redactor
from artcode.evaluation.report import build_run_report, write_run_report
from artcode.evaluation import report as report_module


def _metric(value, source="computed") -> MetricValue:
    return MetricValue(value, source if value is not None else "missing")


def _attempt(task_id: str, number: int, *, passed: bool, tokens: int | None) -> AttemptResult:
    metrics = AttemptMetrics(
        passed=_metric(passed),
        verifier_pass_rate=_metric(1.0 if passed else 0.5),
        model_turns=_metric(2),
        tool_calls=_metric(3),
        tool_errors=_metric(0),
        repeated_tool_calls=_metric(1),
        permission_denials=_metric(0),
        context_events=_metric(0),
        context_before_tokens=_metric(None),
        context_after_tokens=_metric(None),
        context_tokens_saved=_metric(None),
        prompt_tokens=_metric(tokens),
        completion_tokens=_metric(10 if tokens is not None else None),
        total_tokens=_metric(tokens),
        duration_ms=_metric(100),
        judge_score=_metric(None),
        permission_overhead_proxy=_metric(0),
        context_savings_rate=_metric(None),
        permission_confirmations=MetricValue(None, "unavailable"),
    )
    return AttemptResult(
        "run",
        task_id,
        number,
        AttemptStatus.PASSED if passed else AttemptStatus.VERIFICATION_FAILED,
        "natural",
        "done",
        "",
        "workspaces/x",
        "session",
        "traces/x.jsonl",
        "attempts/x.json",
        "workspaces/x-changes.json",
        (),
        metrics,
        JudgeResult.disabled(),
        (),
    )


def test_report_aggregate_and_markdown_agree(benchmark_file: Path, tmp_path: Path) -> None:
    benchmark = load_benchmark(benchmark_file)
    attempts = (
        _attempt("task-one", 1, passed=True, tokens=100),
        _attempt("task-one", 2, passed=False, tokens=300),
        _attempt("task-one", 3, passed=True, tokens=None),
    )
    report = build_run_report(
        benchmark,
        attempts,
        run_id="run",
        model={"model": "fake"},
        started_at="2026-01-01T00:00:00Z",
    )
    json_path, markdown_path = write_run_report(tmp_path, report, redactor=Redactor())
    saved = json.loads(json_path.read_text(encoding="utf-8"))
    assert saved["aggregate"]["success_rate"] == pytest.approx(2 / 3)
    assert saved["aggregate"]["metrics"]["total_tokens"] == {
        "sample_count": 2,
        "mean": 200,
        "min": 100,
        "max": 300,
    }
    assert saved["chta"]["harness_status"] == "complete"
    assert saved["chta"]["permission_confirmations"]["source"] == "unavailable"
    assert "0.67" in markdown_path.read_text(encoding="utf-8")


def test_compare_direction_and_incompatible_guard(benchmark_file: Path) -> None:
    benchmark = load_benchmark(benchmark_file)
    baseline = build_run_report(
        benchmark,
        (_attempt("task-one", 1, passed=False, tokens=1000),),
        run_id="base",
        model={},
        started_at="x",
    )
    candidate = build_run_report(
        benchmark,
        (_attempt("task-one", 1, passed=True, tokens=500),),
        run_id="candidate",
        model={},
        started_at="y",
    )
    comparison = compare_reports(baseline, candidate)
    assert comparison["overall"]["success_rate"]["classification"] == "improved"
    assert comparison["overall"]["total_tokens"]["classification"] == "improved"
    incompatible = copy.deepcopy(candidate)
    incompatible["benchmark"]["fingerprint"] = "different"
    with pytest.raises(ReportComparisonError):
        compare_reports(baseline, incompatible)
    assert not compare_reports(baseline, incompatible, allow_incompatible=True)["compatible"]


def test_load_report_rejects_wrong_schema(tmp_path: Path) -> None:
    path = tmp_path / "report.json"
    path.write_text('{"schema_version": 99}', encoding="utf-8")
    with pytest.raises(ReportComparisonError):
        load_report(path)


def test_atomic_report_failure_keeps_previous_file(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "report.json"
    path.write_text("old", encoding="utf-8")

    def fail_replace(source, destination):
        raise OSError("injected replace failure")

    monkeypatch.setattr(report_module.os, "replace", fail_replace)
    with pytest.raises(OSError, match="injected"):
        report_module.atomic_write_text(path, "new")
    assert path.read_text(encoding="utf-8") == "old"
