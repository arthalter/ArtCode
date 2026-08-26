from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any, Iterable

from .models import AttemptResult, BenchmarkSpec, to_jsonable
from .redaction import Redactor


REPORT_SCHEMA_VERSION = 1
_AGGREGATE_METRICS = (
    "total_tokens",
    "model_turns",
    "tool_calls",
    "tool_errors",
    "repeated_tool_calls",
    "permission_denials",
    "permission_overhead_proxy",
    "context_tokens_saved",
    "context_savings_rate",
    "duration_ms",
    "judge_score",
)


def build_run_report(
    benchmark: BenchmarkSpec,
    attempts: Iterable[AttemptResult],
    *,
    run_id: str,
    model: dict[str, Any],
    started_at: str,
    finished_at: str | None = None,
    interrupted: bool = False,
    repository: Path | None = None,
) -> dict[str, Any]:
    attempt_values = tuple(attempts)
    finished = finished_at or datetime.now(timezone.utc).isoformat()
    task_reports: list[dict[str, Any]] = []
    for task in benchmark.tasks:
        selected = tuple(item for item in attempt_values if item.task_id == task.id)
        task_reports.append(
            {
                "task_id": task.id,
                "tags": list(task.tags),
                "attempt_count": len(selected),
                "aggregate": aggregate_attempts(selected),
            }
        )
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "run_id": run_id,
        "started_at": started_at,
        "finished_at": finished,
        "interrupted": interrupted,
        "benchmark": {
            "version": benchmark.version,
            "name": benchmark.name,
            "description": benchmark.description,
            "source": benchmark.source.name,
            "fingerprint": benchmark.fingerprint,
            "task_count": len(benchmark.tasks),
        },
        "code": git_metadata(repository),
        "environment": {
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "platform": sys.platform,
            "machine": platform.machine(),
        },
        "model": model,
        "aggregate": aggregate_attempts(attempt_values),
        "chta": build_chta_summary(attempt_values, interrupted=interrupted),
        "tasks": task_reports,
        "attempts": [to_jsonable(item) for item in attempt_values],
    }


def build_chta_summary(
    attempts: Iterable[AttemptResult],
    *,
    interrupted: bool = False,
) -> dict[str, Any]:
    values = tuple(attempts)
    aggregate = aggregate_attempts(values)
    metrics = aggregate["metrics"]
    return {
        "harness_status": "partial" if interrupted else "complete",
        "attempt_count": aggregate["attempt_count"],
        "task_success_rate": aggregate["success_rate"],
        "permission_denials": metrics["permission_denials"],
        "permission_overhead_proxy": metrics["permission_overhead_proxy"],
        "permission_confirmations": {
            "value": None,
            "source": "unavailable",
            "reason": "当前无人值守评测 Trace 未提供人工审批事件",
        },
        "context_tokens_saved": metrics["context_tokens_saved"],
        "context_savings_rate": metrics["context_savings_rate"],
        "metrics": {
            name: metrics[name]
            for name in (
                "total_tokens",
                "model_turns",
                "tool_calls",
                "tool_errors",
                "repeated_tool_calls",
                "duration_ms",
            )
        },
    }


def aggregate_attempts(attempts: Iterable[AttemptResult]) -> dict[str, Any]:
    values = tuple(attempts)
    count = len(values)
    passed = sum(item.status.value == "passed" for item in values)
    failures: dict[str, int] = {}
    for item in values:
        failures[item.status.value] = failures.get(item.status.value, 0) + 1
    metrics: dict[str, Any] = {}
    for name in _AGGREGATE_METRICS:
        samples: list[int | float] = []
        for item in values:
            metric = getattr(item.metrics, name).value
            if isinstance(metric, bool) or not isinstance(metric, (int, float)):
                continue
            samples.append(metric)
        metrics[name] = _summarize(samples)
    return {
        "attempt_count": count,
        "passed_count": passed,
        "failed_count": count - passed,
        "success_rate": passed / count if count else None,
        "status_distribution": failures,
        "metrics": metrics,
    }


def write_run_report(
    output_dir: Path,
    report: dict[str, Any],
    *,
    redactor: Redactor,
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_report = redactor.redact_value(report)
    json_path = output_dir / "report.json"
    markdown_path = output_dir / "report.md"
    atomic_write_text(
        json_path,
        json.dumps(safe_report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    atomic_write_text(markdown_path, render_markdown(safe_report))
    return json_path, markdown_path


def write_attempt(path: Path, attempt: AttemptResult, *, redactor: Redactor) -> None:
    payload = redactor.redact_value(to_jsonable(attempt))
    atomic_write_text(
        path,
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def write_json(path: Path, payload: Any, *, redactor: Redactor) -> None:
    atomic_write_text(
        path,
        json.dumps(
            redactor.redact_value(to_jsonable(payload)),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        directory_descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except Exception:
        try:
            temp_path.unlink(missing_ok=True)
        finally:
            raise


def render_markdown(report: dict[str, Any]) -> str:
    benchmark = report["benchmark"]
    aggregate = report["aggregate"]
    lines = [
        f"# Agent 评测报告：{benchmark['name']}",
        "",
        f"- Run ID：`{report['run_id']}`",
        f"- Benchmark 指纹：`{benchmark['fingerprint']}`",
        f"- 开始时间：{report['started_at']}",
        f"- 结束时间：{report['finished_at']}",
        f"- 中断：{'是' if report.get('interrupted') else '否'}",
        "",
        "## 总览",
        "",
        "| 范围 | 尝试 | 通过 | 成功率 | 平均 Token | 平均轮次 | 平均工具调用 | 平均重复调用 | 平均耗时(ms) | Judge 均分 |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        _aggregate_row("总体", aggregate),
        "",
        "## 逐任务",
        "",
        "| 任务 | 尝试 | 通过 | 成功率 | Token | 轮次 | 工具调用 | 重复调用 | 耗时(ms) | Judge |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for task in report.get("tasks", []):
        lines.append(_aggregate_row(task["task_id"], task["aggregate"]))
    lines.extend(["", "## 失败分布", ""])
    distribution = aggregate.get("status_distribution", {})
    if distribution:
        for status, count in sorted(distribution.items()):
            lines.append(f"- `{status}`：{count}")
    else:
        lines.append("- 无尝试")
    lines.extend(["", "## chTA 摘要", ""])
    aggregate_metrics = aggregate.get("metrics", {})
    lines.extend(
        [
            f"- 权限拒绝：{_number(aggregate_metrics.get('permission_denials', {}).get('mean'))}",
            f"- 工具错误：{_number(aggregate_metrics.get('tool_errors', {}).get('mean'))}",
            f"- 权限成本代理：{_number(aggregate_metrics.get('permission_overhead_proxy', {}).get('mean'))} "
            "（权限拒绝数 + 工具错误数，不等同于人工确认次数）",
            "- 人工确认次数：N/A（当前无人值守评测 Trace 未提供审批事件）",
            f"- 上下文节省 Token：{_number(aggregate_metrics.get('context_tokens_saved', {}).get('mean'))}",
            f"- 上下文节省率：{_number(aggregate_metrics.get('context_savings_rate', {}).get('mean'))}",
        ]
    )
    lines.extend(["", "## 尝试明细", ""])
    for attempt in report.get("attempts", []):
        metrics = attempt["metrics"]
        lines.extend(
            [
                f"### {attempt['task_id']} / #{attempt['attempt']}",
                "",
                f"- 状态：`{attempt['status']}`",
                f"- 终止原因：`{attempt.get('stop_reason') or 'null'}`",
                f"- Token：{_metric_display(metrics['total_tokens'])}",
                f"- 模型轮次：{_metric_display(metrics['model_turns'])}",
                f"- 工具调用：{_metric_display(metrics['tool_calls'])}",
                f"- 权限拒绝：{_metric_display(metrics['permission_denials'])}",
                f"- 上下文节省 Token：{_metric_display(metrics['context_tokens_saved'])}",
                f"- Trace：`{attempt['trace_path']}`",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def git_metadata(repository: Path | None) -> dict[str, Any]:
    if repository is None:
        return {"commit": None, "dirty": None}
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=repository,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        )
        return {"commit": commit, "dirty": dirty}
    except (OSError, subprocess.SubprocessError):
        return {"commit": None, "dirty": None}


def _summarize(samples: list[int | float]) -> dict[str, Any]:
    if not samples:
        return {"sample_count": 0, "mean": None, "min": None, "max": None}
    return {
        "sample_count": len(samples),
        "mean": mean(samples),
        "min": min(samples),
        "max": max(samples),
    }


def _aggregate_row(label: str, aggregate: dict[str, Any]) -> str:
    metrics = aggregate["metrics"]
    return "| {} | {} | {} | {} | {} | {} | {} | {} | {} | {} |".format(
        label,
        aggregate["attempt_count"],
        aggregate["passed_count"],
        _number(aggregate["success_rate"]),
        _number(metrics["total_tokens"]["mean"]),
        _number(metrics["model_turns"]["mean"]),
        _number(metrics["tool_calls"]["mean"]),
        _number(metrics["repeated_tool_calls"]["mean"]),
        _number(metrics["duration_ms"]["mean"]),
        _number(metrics["judge_score"]["mean"]),
    )


def _number(value: Any) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def _metric_display(metric: dict[str, Any]) -> str:
    return f"{_number(metric.get('value'))} ({metric.get('source', 'missing')})"


__all__ = [
    "REPORT_SCHEMA_VERSION",
    "aggregate_attempts",
    "atomic_write_text",
    "build_run_report",
    "build_chta_summary",
    "git_metadata",
    "render_markdown",
    "write_attempt",
    "write_json",
    "write_run_report",
]
