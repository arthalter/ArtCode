from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from artcode.evaluation.chta.swebench_live import (
    OfficialSWEbenchAdapter,
    load_swebench_lock,
    run_gold_preflight,
)


ROOT = Path(__file__).resolve().parents[2]


def test_swebench_lock_is_fixed_and_has_sufficient_candidates() -> None:
    lock = load_swebench_lock(ROOT / "benchmarks" / "chTA" / "swebench" / "lock.yml")
    assert lock.sample_size == 6
    assert lock.gold_repetitions == 3
    assert lock.seed == 20260813
    assert len(lock.candidates) == 30
    assert len(set(lock.candidates)) == 30


def test_official_adapter_uses_locked_cli_and_parses_official_report(tmp_path: Path) -> None:
    commands = []

    def runner(command, *, cwd, **kwargs):
        commands.append(command)
        run_id = command[command.index("--run_id") + 1]
        instance_id = command[command.index("--instance_ids") + 1]
        report = cwd / "logs" / "run_evaluation" / run_id / "gold" / instance_id / "report.json"
        report.parent.mkdir(parents=True)
        report.write_text(
            json.dumps({instance_id: {"resolved": True}}), encoding="utf-8"
        )
        return subprocess.CompletedProcess(command, 0, "official ok", "")

    adapter = OfficialSWEbenchAdapter(
        python=Path("/official/python"),
        repository=tmp_path / "official",
        dataset_json=tmp_path / "dataset.json",
        namespace="starryzhang",
        output_dir=tmp_path / "runs",
        runner=runner,
    )
    result = adapter.run_gold("owner__repo-1", 1)

    assert result.resolved is True
    assert result.status == "resolved"
    assert "swebench.harness.run_evaluation" in commands[0]
    assert commands[0][commands[0].index("--predictions_path") + 1] == "gold"
    assert commands[0][commands[0].index("--namespace") + 1] == "starryzhang"


def test_official_adapter_parses_current_summary_report(tmp_path: Path) -> None:
    def runner(command, *, cwd, **kwargs):
        run_id = command[command.index("--run_id") + 1]
        instance_id = command[command.index("--instance_ids") + 1]
        (cwd / f"gold.{run_id}.json").write_text(
            json.dumps({"schema_version": 2, "resolved_ids": [instance_id]}),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, "official ok", "")

    result = OfficialSWEbenchAdapter(
        python=Path("/official/python"),
        repository=tmp_path / "official",
        dataset_json=tmp_path / "dataset.json",
        namespace="starryzhang",
        output_dir=tmp_path / "runs",
        runner=runner,
    ).run_gold("owner__repo-2", 1)

    assert result.resolved is True
    assert Path(result.report_path).name.startswith("gold.gold-")


def test_gold_preflight_locks_only_three_consecutive_official_passes(
    tmp_path: Path,
) -> None:
    lock = load_swebench_lock(ROOT / "benchmarks" / "chTA" / "swebench" / "lock.yml")

    class Adapter:
        def run_gold(self, instance_id, repetition):
            from artcode.evaluation.chta.swebench_live import OfficialRunResult

            valid = not instance_id.endswith("28577")
            return OfficialRunResult(
                instance_id,
                repetition,
                valid,
                "resolved" if valid else "unresolved",
                ("official",),
                "report.json",
                "command.log",
            )

    result = run_gold_preflight(Adapter(), lock, tmp_path / "gold-lock.json")

    assert result.status == "complete"
    assert len(result.locked_instances) == 6
    assert "matplotlib__matplotlib-28577" not in result.locked_instances
    assert result.instances[0].exclusion_reason


def test_swebench_lock_rejects_unknown_fields(tmp_path: Path) -> None:
    path = tmp_path / "lock.yml"
    path.write_text(
        "version: 1\nnamespace: x\nsample_size: 1\ngold_repetitions: 3\nseed: 1\ncandidates: [x]\nunknown: true\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="字段"):
        load_swebench_lock(path)
