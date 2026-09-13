from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RetentionProbe:
    id: str
    category: str
    expected: str
    expected_sha256: str
    required_role: str | None


@dataclass(frozen=True)
class RetentionProbeResult:
    instance_id: str
    profile: str
    probe_id: str
    category: str
    passed: bool
    expected_sha256: str
    evidence_sha256: str | None
    evidence_role: str | None
    evidence_path: str


@dataclass(frozen=True)
class RetentionAggregate:
    profile: str
    passed: int
    total: int
    rate: float | None


def build_retention_probes(instance: dict[str, Any]) -> tuple[str, tuple[RetentionProbe, ...]]:
    instance_id = _required(instance, "instance_id")
    problem = _required(instance, "problem_statement")
    constraint = _first_constraint(problem, str(instance.get("hints_text") or ""))
    files = _patch_files(str(instance.get("patch") or ""), str(instance.get("test_patch") or ""))
    if not files:
        raise ValueError(f"{instance_id} 无法从 patch 提取相关文件")
    tests = _test_targets(instance)
    if not tests:
        raise ValueError(f"{instance_id} 缺少 FAIL_TO_PASS 测试目标")
    related_files = "\n".join(files)
    test_conclusion = "\n".join(tests)
    values = (
        ("original_requirement", problem, "user"),
        ("key_constraint", constraint, "user"),
        ("related_files", related_files, None),
        ("test_conclusion", test_conclusion, None),
    )
    probes = tuple(
        RetentionProbe(
            f"{instance_id}:{category}",
            category,
            value,
            _sha256(value),
            role,
        )
        for category, value, role in values
    )
    prompt = "\n\n".join(
        [
            f"Original problem requirement:\n{problem}",
            f"Key constraint:\n{constraint}",
            f"Related files:\n{related_files}",
            f"Tests that must pass:\n{test_conclusion}",
        ]
    )
    return prompt, probes


def evaluate_retention_messages(
    instance_id: str,
    profile: str,
    probes: tuple[RetentionProbe, ...],
    messages: list[dict[str, Any]],
    *,
    evidence_path: str,
) -> tuple[RetentionProbeResult, ...]:
    results = []
    for probe in probes:
        match_role = None
        match_value = None
        for message in messages:
            role = message.get("role")
            content = message.get("content")
            if not isinstance(role, str) or not isinstance(content, str):
                continue
            if probe.required_role is not None and role != probe.required_role:
                continue
            if probe.expected in content:
                match_role = role
                match_value = probe.expected
                break
        results.append(
            RetentionProbeResult(
                instance_id,
                profile,
                probe.id,
                probe.category,
                match_value is not None,
                probe.expected_sha256,
                _sha256(match_value) if match_value is not None else None,
                match_role,
                evidence_path,
            )
        )
    return tuple(results)


def aggregate_retention(
    profile: str, results: tuple[RetentionProbeResult, ...]
) -> RetentionAggregate:
    selected = tuple(item for item in results if item.profile == profile)
    passed = sum(item.passed for item in selected)
    return RetentionAggregate(
        profile,
        passed,
        len(selected),
        passed / len(selected) if selected else None,
    )


def load_driver_retention_results(
    path: Path,
    *,
    instance_id: str,
    profile: str,
    probes: tuple[RetentionProbe, ...],
) -> tuple[RetentionProbeResult, ...]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取保留探针驱动结果：{exc}") from exc
    messages = raw.get("messages") if isinstance(raw, dict) else None
    preflight = raw.get("preflight") if isinstance(raw, dict) else None
    if not isinstance(messages, list) or preflight != "all_present":
        raise ValueError("保留探针驱动结果缺少消息或压缩前探针未全部命中")
    return evaluate_retention_messages(
        instance_id,
        profile,
        probes,
        messages,
        evidence_path=str(path),
    )


def _first_constraint(problem: str, hints: str) -> str:
    candidates = [line.strip() for line in hints.splitlines() if line.strip()]
    if not candidates:
        candidates = [
            part.strip()
            for part in re.split(r"(?<=[.!?。！？])\s+|\n+", problem)
            if part.strip()
        ]
    return candidates[0] if candidates else problem


def _patch_files(*patches: str) -> tuple[str, ...]:
    found = []
    for patch in patches:
        for value in re.findall(r"(?m)^\+\+\+ b/(.+)$", patch):
            if value != "/dev/null" and value not in found:
                found.append(value)
    return tuple(found)


def _test_targets(instance: dict[str, Any]) -> tuple[str, ...]:
    value = instance.get("FAIL_TO_PASS")
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            value = [value]
    if not isinstance(value, list):
        return ()
    return tuple(str(item) for item in value if str(item).strip())


def _required(instance: dict[str, Any], key: str) -> str:
    value = instance.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"SWE-bench 实例缺少 {key}")
    return value


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


__all__ = [
    "RetentionAggregate",
    "RetentionProbe",
    "RetentionProbeResult",
    "aggregate_retention",
    "build_retention_probes",
    "evaluate_retention_messages",
    "load_driver_retention_results",
]
