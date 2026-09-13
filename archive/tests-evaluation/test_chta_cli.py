from __future__ import annotations

import json
from pathlib import Path

from artcode.evaluation.chta.runner import ChTARunner
from artcode.evaluation.cli import build_parser, main


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "benchmarks" / "chTA" / "manifest.yml"


def test_chta_validate_prints_locked_fingerprint(capsys) -> None:
    assert main(["chTA", "validate", str(MANIFEST)]) == 0

    output = capsys.readouterr().out
    assert "experiments=3" in output
    assert "sha256=" in output


def test_chta_run_parser_supports_each_experiment() -> None:
    parser = build_parser()

    for experiment in ("mcp", "permission", "swebench", "all"):
        args = parser.parse_args(
            ["chTA", "run", str(MANIFEST), "--experiment", experiment]
        )
        assert args.command == "chTA"
        assert args.chta_command == "run"
        assert args.experiment == experiment


def test_chta_permission_cli_runs_real_production_chain(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    def without_artifact_runtime(self, report_json: Path, run_dir: Path):
        target = run_dir / "report.xlsx"
        target.write_bytes(b"test-workbook-placeholder")
        return target

    monkeypatch.setattr(
        ChTARunner,
        "_write_workbook_or_evidence",
        without_artifact_runtime,
    )
    output = tmp_path / "runs"

    code = main(
        [
            "chTA",
            "run",
            str(MANIFEST),
            "--experiment",
            "permission",
            "--output-dir",
            str(output),
        ]
    )

    assert code == 0
    report_path = next(output.glob("*/report.json"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    result = report["experiments"]["permission"]
    assert result["status"] == "complete"
    assert result["baseline"]["approval_requests"] == 30
    assert result["candidate"]["approval_requests"] == 5
    assert result["candidate"]["rule_hits"] == 25
    assert "status=complete" in capsys.readouterr().out
