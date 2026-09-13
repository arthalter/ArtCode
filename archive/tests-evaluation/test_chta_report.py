from __future__ import annotations

import json
from pathlib import Path

from artcode.evaluation.chta.report import (
    build_chta_report,
    render_chta_markdown,
    write_chta_report_files,
)
from artcode.evaluation.chta.workbook import write_chta_workbook
from artcode.evaluation.manifest import load_chta_manifest


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "benchmarks" / "chTA" / "manifest.yml"


def _complete_experiments() -> dict:
    return {
        "mcp": {
            "status": "complete",
            "evidence_complete": True,
            "profiles": {
                "eager": {"success_rate": 1.0},
                "lazy": {"success_rate": 1.0},
            },
            "comparisons": {
                "first_tool_definition_tokens": {
                    "baseline": 12_000,
                    "candidate": 2_400,
                    "reduction_rate": 0.8,
                },
                "provider_prompt_tokens": {
                    "baseline": 8_000,
                    "candidate": 3_200,
                    "reduction_rate": 0.6,
                },
            },
            "attempts": [],
        },
        "permission": {
            "status": "complete",
            "evidence_complete": True,
            "baseline": {
                "approval_requests": 30,
                "false_allows": 0,
                "false_denials": 0,
            },
            "candidate": {
                "approval_requests": 5,
                "rule_hits": 25,
                "false_allows": 0,
                "false_denials": 0,
            },
            "approval_reduction_rate": 5 / 6,
        },
        "swebench": {
            "status": "complete",
            "evidence_complete": True,
            "profiles": {
                "baseline": {"resolved": 1, "gold_valid": 6, "resolve_rate": 1 / 6},
                "candidate": {"resolved": 2, "gold_valid": 6, "resolve_rate": 1 / 3},
            },
            "retention": {
                "baseline": {"passed": 12, "total": 24, "retention_rate": 0.5},
                "candidate": {"passed": 21, "total": 24, "retention_rate": 0.875},
            },
            "attempts": [],
            "retention_probes": [],
        },
    }


def test_chta_report_emits_separate_official_and_retention_metrics(tmp_path: Path) -> None:
    report = build_chta_report(
        load_chta_manifest(MANIFEST),
        run_id="chta-test",
        experiments=_complete_experiments(),
        evidence_root=tmp_path / "evidence",
    )

    markdown = render_chta_markdown(report)

    assert report["status"] == "complete"
    assert len(report["resume_statements"]) == 3
    assert "首轮工具描述 Token" in markdown
    assert "Provider prompt Token" in markdown
    assert "official resolved 1/6" in markdown
    assert "retention 12/24" in markdown


def test_resume_numbers_are_withheld_when_evidence_is_incomplete(tmp_path: Path) -> None:
    experiments = _complete_experiments()
    experiments["mcp"]["evidence_complete"] = False
    experiments["permission"]["status"] = "partial"
    experiments["swebench"]["status"] = "blocked"
    report = build_chta_report(
        load_chta_manifest(MANIFEST),
        run_id="chta-incomplete",
        experiments=experiments,
        evidence_root=tmp_path / "evidence",
    )

    assert report["status"] == "partial"
    assert report["resume_statements"] == []
    assert "尚无同时通过真实运行" in render_chta_markdown(report)


def test_chta_report_files_are_machine_readable(tmp_path: Path) -> None:
    report = build_chta_report(
        load_chta_manifest(MANIFEST),
        run_id="chta-files",
        experiments=_complete_experiments(),
        evidence_root=tmp_path / "evidence",
    )

    json_path, markdown_path = write_chta_report_files(report, tmp_path / "report")

    assert json.loads(json_path.read_text(encoding="utf-8"))["run_id"] == "chta-files"
    assert markdown_path.read_text(encoding="utf-8").startswith("# chTA")


def test_workbook_requires_supported_runtime(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    report.write_text("{}", encoding="utf-8")

    try:
        write_chta_workbook(
            report,
            tmp_path / "report.xlsx",
            node_binary=tmp_path / "missing-node",
            node_modules=tmp_path / "missing-modules",
        )
    except RuntimeError as exc:
        assert "Node.js runtime" in str(exc)
    else:
        raise AssertionError("缺少受支持 runtime 时不应静默生成工作簿")
