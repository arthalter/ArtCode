from __future__ import annotations

from artcode.evaluation.chta.retention_probes import (
    aggregate_retention,
    build_retention_probes,
    evaluate_retention_messages,
)


def _instance():
    return {
        "instance_id": "owner__repo-1",
        "problem_statement": "Fix parsing. Preserve quoted commas.",
        "hints_text": "Do not change unquoted field behavior.",
        "patch": "diff --git a/parser.py b/parser.py\n--- a/parser.py\n+++ b/parser.py\n",
        "test_patch": "diff --git a/tests/test_parser.py b/tests/test_parser.py\n--- a/tests/test_parser.py\n+++ b/tests/test_parser.py\n",
        "FAIL_TO_PASS": ["tests/test_parser.py::test_quoted_comma"],
    }


def test_task_derived_probes_cover_four_deterministic_categories() -> None:
    prompt, probes = build_retention_probes(_instance())
    assert [item.category for item in probes] == [
        "original_requirement",
        "key_constraint",
        "related_files",
        "test_conclusion",
    ]
    assert all(item.expected in prompt for item in probes)
    assert len({item.expected_sha256 for item in probes}) == 4


def test_retention_separates_content_and_user_role_fidelity() -> None:
    prompt, probes = build_retention_probes(_instance())
    baseline = evaluate_retention_messages(
        "owner__repo-1",
        "baseline",
        probes,
        [{"role": "system", "content": prompt}],
        evidence_path="baseline.json",
    )
    candidate = evaluate_retention_messages(
        "owner__repo-1",
        "candidate",
        probes,
        [{"role": "user", "content": prompt}],
        evidence_path="candidate.json",
    )
    assert aggregate_retention("baseline", baseline).passed == 2
    assert aggregate_retention("candidate", candidate).passed == 4
    assert all(item.evidence_sha256 == item.expected_sha256 for item in candidate)
