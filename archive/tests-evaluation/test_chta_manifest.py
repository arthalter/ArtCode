from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from artcode.evaluation.manifest import BenchmarkValidationError, load_chta_manifest
from artcode.evaluation.models import ChTAExperimentKind


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "benchmarks" / "chTA" / "manifest.yml"


def _write(tmp_path: Path, raw: dict) -> Path:
    path = tmp_path / "manifest.yml"
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return path


def _raw() -> dict:
    return yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))


def test_chta_manifest_locks_three_comparable_experiments() -> None:
    manifest = load_chta_manifest(MANIFEST)

    assert len(manifest.fingerprint) == 64
    assert {item.kind for item in manifest.experiments} == set(ChTAExperimentKind)
    assert manifest.revisions.baseline_commit.startswith("a987d15")
    assert manifest.revisions.candidate_commit.startswith("92a28a7")
    assert manifest.experiments[0].parameters["tool_count"] == 120


@pytest.mark.parametrize(
    "mutation",
    [
        lambda raw: raw.update({"unknown": True}),
        lambda raw: raw["experiments"][0].update({"unexpected": 1}),
        lambda raw: raw["experiments"][0]["parameters"].update({"fake": 1}),
    ],
)
def test_chta_manifest_rejects_unknown_fields(tmp_path: Path, mutation) -> None:
    raw = _raw()
    mutation(raw)
    with pytest.raises(BenchmarkValidationError, match="未知字段"):
        load_chta_manifest(_write(tmp_path, raw))


def test_chta_manifest_rejects_duplicate_ids_and_tasks(tmp_path: Path) -> None:
    raw = _raw()
    duplicate = deepcopy(raw["experiments"][0])
    raw["experiments"].append(duplicate)
    raw["experiments"][0]["tasks"].append(raw["experiments"][0]["tasks"][0])

    with pytest.raises(BenchmarkValidationError) as caught:
        load_chta_manifest(_write(tmp_path, raw))

    assert "id 重复" in str(caught.value)
    assert "不能包含重复值" in str(caught.value)


@pytest.mark.parametrize(
    "field,value",
    [
        ("swebench_revision", "main"),
        ("baseline_commit", "a987d15"),
        ("candidate_commit", "not-a-revision"),
    ],
)
def test_chta_manifest_rejects_unlocked_revisions(
    tmp_path: Path, field: str, value: str
) -> None:
    raw = _raw()
    raw["revisions"][field] = value
    with pytest.raises(BenchmarkValidationError, match="40 位 Git revision"):
        load_chta_manifest(_write(tmp_path, raw))


def test_chta_manifest_rejects_incomplete_ab_pair(tmp_path: Path) -> None:
    raw = _raw()
    raw["experiments"][0]["candidate"] = deepcopy(
        raw["experiments"][0]["baseline"]
    )
    with pytest.raises(BenchmarkValidationError, match="不同 profile 和机制"):
        load_chta_manifest(_write(tmp_path, raw))
