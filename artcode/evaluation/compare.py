from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .redaction import Redactor
from .report import REPORT_SCHEMA_VERSION, atomic_write_text


class ReportComparisonError(ValueError):
    pass


_DIRECTIONS = {
    "success_rate": 1,
    "total_tokens": -1,
    "model_turns": -1,
    "tool_calls": -1,
    "repeated_tool_calls": -1,
    "duration_ms": -1,
    "judge_score": 1,
}


def load_report(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReportComparisonError(f"无法读取报告 {path}：{exc}") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != REPORT_SCHEMA_VERSION:
        raise ReportComparisonError(f"报告 schema 不兼容：{path}")
    benchmark = raw.get("benchmark")
    if not isinstance(benchmark, dict) or not isinstance(benchmark.get("fingerprint"), str):
        raise ReportComparisonError(f"报告缺少 Benchmark 指纹：{path}")
    if not isinstance(raw.get("aggregate"), dict) or not isinstance(raw.get("tasks"), list):
        raise ReportComparisonError(f"报告结构不完整：{path}")
    return raw


def compare_reports(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    *,
    allow_incompatible: bool = False,
) -> dict[str, Any]:
    baseline_fingerprint = baseline["benchmark"]["fingerprint"]
    candidate_fingerprint = candidate["benchmark"]["fingerprint"]
    compatible = baseline_fingerprint == candidate_fingerprint
    if not compatible and not allow_incompatible:
        raise ReportComparisonError("Benchmark 指纹不同，默认拒绝直接比较")

    baseline_tasks = {item["task_id"]: item for item in baseline["tasks"]}
    candidate_tasks = {item["task_id"]: item for item in candidate["tasks"]}
    common = sorted(set(baseline_tasks) & set(candidate_tasks))
    task_diffs = [
        {
            "task_id": task_id,
            "metrics": _compare_aggregate(
                baseline_tasks[task_id]["aggregate"],
                candidate_tasks[task_id]["aggregate"],
            ),
        }
        for task_id in common
    ]
    overall = (
        _compare_aggregate(baseline["aggregate"], candidate["aggregate"])
        if compatible
        else _not_comparable_aggregate()
    )
    return {
        "schema_version": 1,
        "compatible": compatible,
        "baseline": {
            "run_id": baseline.get("run_id"),
            "benchmark_fingerprint": baseline_fingerprint,
        },
        "candidate": {
            "run_id": candidate.get("run_id"),
            "benchmark_fingerprint": candidate_fingerprint,
        },
        "overall": overall,
        "tasks": task_diffs,
        "baseline_only_tasks": sorted(set(baseline_tasks) - set(candidate_tasks)),
        "candidate_only_tasks": sorted(set(candidate_tasks) - set(baseline_tasks)),
    }


def write_comparison(
    output_dir: Path,
    comparison: dict[str, Any],
    *,
    redactor: Redactor,
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    safe = redactor.redact_value(comparison)
    json_path = output_dir / "compare.json"
    markdown_path = output_dir / "compare.md"
    atomic_write_text(
        json_path,
        json.dumps(safe, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    atomic_write_text(markdown_path, render_comparison(safe))
    return json_path, markdown_path


def render_comparison(comparison: dict[str, Any]) -> str:
    lines = [
        "# Agent 评测回归对比",
        "",
        f"- Benchmark 兼容：{'是' if comparison['compatible'] else '否'}",
        f"- Baseline：`{comparison['baseline']['run_id']}`",
        f"- Candidate：`{comparison['candidate']['run_id']}`",
        "",
        "## 总体变化",
        "",
        "| 指标 | Baseline | Candidate | Delta | 判断 |",
        "|---|---:|---:|---:|---|",
    ]
    for name, value in comparison["overall"].items():
        lines.append(
            f"| {name} | {_display(value['baseline'])} | {_display(value['candidate'])} | "
            f"{_display(value['delta'])} | {value['classification']} |"
        )
    lines.extend(["", "## 逐任务", ""])
    for task in comparison["tasks"]:
        lines.extend([f"### {task['task_id']}", ""])
        for name, value in task["metrics"].items():
            lines.append(
                f"- `{name}`：{_display(value['baseline'])} → {_display(value['candidate'])} "
                f"(Δ {_display(value['delta'])}, {value['classification']})"
            )
        lines.append("")
    if comparison["baseline_only_tasks"] or comparison["candidate_only_tasks"]:
        lines.extend(
            [
                "## 不可比较任务",
                "",
                f"- 仅 Baseline：{', '.join(comparison['baseline_only_tasks']) or '无'}",
                f"- 仅 Candidate：{', '.join(comparison['candidate_only_tasks']) or '无'}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _compare_aggregate(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, direction in _DIRECTIONS.items():
        if name == "success_rate":
            old = baseline.get("success_rate")
            new = candidate.get("success_rate")
        else:
            old = baseline.get("metrics", {}).get(name, {}).get("mean")
            new = candidate.get("metrics", {}).get(name, {}).get("mean")
        delta = new - old if _number(old) and _number(new) else None
        if delta is None:
            classification = "not_comparable"
        elif delta == 0:
            classification = "unchanged"
        elif delta * direction > 0:
            classification = "improved"
        else:
            classification = "regressed"
        result[name] = {
            "baseline": old,
            "candidate": new,
            "delta": delta,
            "classification": classification,
        }
    return result


def _not_comparable_aggregate() -> dict[str, Any]:
    return {
        name: {
            "baseline": None,
            "candidate": None,
            "delta": None,
            "classification": "not_comparable",
        }
        for name in _DIRECTIONS
    }


def _number(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float))


def _display(value: Any) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


__all__ = [
    "ReportComparisonError",
    "compare_reports",
    "load_report",
    "render_comparison",
    "write_comparison",
]
