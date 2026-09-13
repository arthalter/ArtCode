from __future__ import annotations

from pathlib import Path

import pytest

from artcode.evaluation.chta.permission_experiment import (
    PermissionExperimentRunner,
    load_permission_operations,
)


ROOT = Path(__file__).resolve().parents[2]
OPERATIONS = ROOT / "benchmarks" / "chTA" / "permission" / "operations.yml"


async def test_permission_replay_uses_real_chain_and_exact_rule_events(
    tmp_path: Path,
) -> None:
    operations = load_permission_operations(OPERATIONS)
    result = await PermissionExperimentRunner(
        operations,
        output_dir=tmp_path / "permission",
    ).run()

    assert result.status == "complete"
    assert result.baseline.normal_operation_count == 30
    assert result.candidate.normal_operation_count == 30
    assert result.baseline.approval_requests == 30
    assert result.baseline.allow_once == 30
    assert result.candidate.approval_requests == 5
    assert result.candidate.allow_always == 5
    assert result.candidate.rule_writes == 5
    assert result.candidate.rule_hits == 25
    assert result.approval_reduction_rate == pytest.approx(25 / 30)
    assert result.baseline.false_allows == result.candidate.false_allows == 0
    assert result.baseline.false_denials == result.candidate.false_denials == 0
    assert not (tmp_path / "permission" / "always" / "workspace" / "alpha.txt.bak").exists()
    assert not (
        tmp_path / "permission" / "always" / "workspace" / "command.log.extra"
    ).exists()


def test_permission_operation_manifest_is_strict(tmp_path: Path) -> None:
    path = tmp_path / "bad.yml"
    path.write_text("version: 1\ntargets: []\nunknown: true\n", encoding="utf-8")
    with pytest.raises(ValueError, match="字段"):
        load_permission_operations(path)
