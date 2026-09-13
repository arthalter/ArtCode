from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from artcode.evaluation.models import ChTAManifest, to_jsonable
from artcode.evaluation.report import atomic_write_text


def build_chta_report(
    manifest: ChTAManifest,
    *,
    run_id: str,
    experiments: dict[str, Any],
    evidence_root: Path,
) -> dict[str, Any]:
    normalized = {
        key: to_jsonable(value) if is_dataclass(value) else _jsonable(value)
        for key, value in experiments.items()
    }
    statuses = [
        value.get("status", "blocked")
        for value in normalized.values()
        if isinstance(value, dict)
    ]
    status = (
        "complete"
        if statuses and all(value == "complete" for value in statuses)
        else "blocked"
        if not statuses or all(value == "blocked" for value in statuses)
        else "partial"
    )
    report = {
        "schema_version": 1,
        "run_id": run_id,
        "status": status,
        "manifest": {
            "name": manifest.name,
            "fingerprint": manifest.fingerprint,
            "source": str(manifest.source),
            "model": to_jsonable(manifest.model),
            "budget": to_jsonable(manifest.budget),
            "revisions": to_jsonable(manifest.revisions),
        },
        "experiments": normalized,
        "evidence_root": str(evidence_root),
    }
    report["resume_statements"] = build_resume_statements(report)
    return report


def build_resume_statements(report: dict[str, Any]) -> list[str]:
    statements: list[str] = []
    experiments = report.get("experiments", {})
    mcp = experiments.get("mcp") if isinstance(experiments, dict) else None
    if _experiment_evidence_ready(mcp):
        comparison = mcp.get("comparisons", {}).get("first_tool_definition_tokens", {})
        prompt_comparison = mcp.get("comparisons", {}).get("provider_prompt_tokens", {})
        rate = comparison.get("reduction_rate")
        prompt_rate = prompt_comparison.get("reduction_rate")
        profiles = mcp.get("profiles", {})
        baseline_rate = _profile_success_rate(profiles, "eager")
        candidate_rate = _profile_success_rate(profiles, "lazy")
        if (
            isinstance(rate, (int, float))
            and isinstance(prompt_rate, (int, float))
            and baseline_rate is not None
            and candidate_rate is not None
        ):
            statements.append(
                "在 120 工具 MCP 目录的真实 A/B 中，通过会话级延迟发现将首轮工具描述 Token "
                f"降低 {rate:.1%}、服务端模型输入 Token 降低 {prompt_rate:.1%}，"
                f"任务成功率由 {baseline_rate:.1%} 变为 {candidate_rate:.1%}。"
            )

    permission = experiments.get("permission") if isinstance(experiments, dict) else None
    if _experiment_evidence_ready(permission):
        baseline = permission.get("baseline", {})
        candidate = permission.get("candidate", {})
        rate = permission.get("approval_reduction_rate")
        if (
            isinstance(rate, (int, float))
            and baseline.get("false_allows") == 0
            and candidate.get("false_allows") == 0
        ):
            statements.append(
                "在 30 次真实权限链路回放中，精确规则复用将审批请求从 "
                f"{baseline.get('approval_requests')} 次降至 {candidate.get('approval_requests')} 次"
                f"（降低 {rate:.1%}），且危险/越界负向控制误放行为 0。"
            )

    swebench = experiments.get("swebench") if isinstance(experiments, dict) else None
    if _experiment_evidence_ready(swebench):
        profiles = swebench.get("profiles", {})
        retention = swebench.get("retention", {})
        if profiles and retention:
            names = list(profiles)
            if len(names) == 2:
                before, after = names
                statements.append(
                    "在 6 个 gold-valid SWE-bench-Live Python pilot 上，官方解决率由 "
                    f"{_percent(profiles[before].get('resolve_rate'))} 变为 "
                    f"{_percent(profiles[after].get('resolve_rate'))}；独立信息保留率由 "
                    f"{_percent(retention[before].get('retention_rate'))} 变为 "
                    f"{_percent(retention[after].get('retention_rate'))}。"
                )
    return statements


def render_chta_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# chTA：Agent 系统效率与信息保真评测报告",
        "",
        f"- Run ID：`{report.get('run_id', '')}`",
        f"- 状态：`{report.get('status', '')}`",
        f"- 清单指纹：`{report.get('manifest', {}).get('fingerprint', '')}`",
        "",
        "## 实验状态",
        "",
        "| 实验 | 状态 |",
        "|---|---|",
    ]
    experiments = report.get("experiments", {})
    for name in ("mcp", "permission", "swebench"):
        value = experiments.get(name, {}) if isinstance(experiments, dict) else {}
        lines.append(f"| {name} | {value.get('status', 'blocked')} |")
    lines.extend(["", "## 核心结果", ""])
    _append_mcp_markdown(lines, experiments.get("mcp", {}))
    _append_permission_markdown(lines, experiments.get("permission", {}))
    _append_swebench_markdown(lines, experiments.get("swebench", {}))
    lines.extend(["", "## 可用于简历", ""])
    statements = report.get("resume_statements", [])
    if statements:
        lines.extend(f"- {statement}" for statement in statements)
    else:
        lines.append("- N/A：尚无同时通过真实运行、证据完整和安全门槛的数字句。")
    lines.extend(
        [
            "",
            "## 证据根目录",
            "",
            f"`{report.get('evidence_root', '')}`",
            "",
        ]
    )
    return "\n".join(lines)


def write_chta_report_files(
    report: dict[str, Any],
    output_dir: Path,
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "report.json"
    markdown_path = output_dir / "report.md"
    atomic_write_text(
        json_path,
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    atomic_write_text(markdown_path, render_chta_markdown(report))
    return json_path, markdown_path


def _append_mcp_markdown(lines: list[str], value: dict[str, Any]) -> None:
    lines.extend(["### MCP 延迟加载", ""])
    comparison = value.get("comparisons", {}).get("first_tool_definition_tokens", {})
    lines.append(
        "- 首轮工具描述 Token："
        f"{comparison.get('baseline', 'N/A')} → {comparison.get('candidate', 'N/A')}；"
        f"降幅 {_percent(comparison.get('reduction_rate'))}。"
    )
    prompt = value.get("comparisons", {}).get("provider_prompt_tokens", {})
    lines.append(
        "- Provider prompt Token："
        f"{prompt.get('baseline', 'N/A')} → {prompt.get('candidate', 'N/A')}；"
        f"降幅 {_percent(prompt.get('reduction_rate'))}。"
    )


def _append_permission_markdown(lines: list[str], value: dict[str, Any]) -> None:
    lines.extend(["", "### 权限审批复用", ""])
    baseline = value.get("baseline", {})
    candidate = value.get("candidate", {})
    lines.append(
        "- 审批请求："
        f"{baseline.get('approval_requests', 'N/A')} → {candidate.get('approval_requests', 'N/A')}；"
        f"降幅 {_percent(value.get('approval_reduction_rate'))}。"
    )
    lines.append(
        f"- 规则命中：{candidate.get('rule_hits', 'N/A')}；"
        f"误放行：{candidate.get('false_allows', 'N/A')}。"
    )


def _append_swebench_markdown(lines: list[str], value: dict[str, Any]) -> None:
    lines.extend(["", "### SWE-bench-Live 与信息保留", ""])
    profiles = value.get("profiles", {})
    retention = value.get("retention", {})
    if not profiles:
        lines.append("- N/A")
        return
    for profile, metrics in profiles.items():
        related = retention.get(profile, {})
        lines.append(
            f"- {profile}：official resolved {metrics.get('resolved', 'N/A')}/"
            f"{metrics.get('gold_valid', 'N/A')}（{_percent(metrics.get('resolve_rate'))}）；"
            f"retention {related.get('passed', 'N/A')}/{related.get('total', 'N/A')}"
            f"（{_percent(related.get('retention_rate'))}）。"
        )


def _experiment_evidence_ready(value: Any) -> bool:
    if not isinstance(value, dict) or value.get("status") != "complete":
        return False
    return value.get("evidence_complete", False) is True


def _profile_success_rate(profiles: dict[str, Any], name: str) -> float | None:
    value = profiles.get(name, {}).get("success_rate") if isinstance(profiles, dict) else None
    return float(value) if isinstance(value, (int, float)) else None


def _percent(value: Any) -> str:
    return f"{value:.1%}" if isinstance(value, (int, float)) else "N/A"


def _jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


__all__ = [
    "build_chta_report",
    "build_resume_statements",
    "render_chta_markdown",
    "write_chta_report_files",
]
