#!/usr/bin/env python3
"""Validate the incremental ch14 behavior matrix."""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Mapping
from pathlib import Path, PurePosixPath
import re
import sys
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MATRIX = ROOT / "tests" / "behavior" / "ch14_matrix.yml"
TASK_PATTERN = re.compile(r"T(?:[1-9]|1[0-5])\Z")
REQUIREMENT_PATTERN = re.compile(r"(?:F(?:[1-9]|[1-8][0-9]|9[0-8])|N(?:[1-9]|1[0-6])|AC(?:[1-9]|1[0-9]|2[0-5]))\Z")
OWNERS = {"Application", "Session", "Agent", "Model", "Tool", "Workspace", "Skill", "Subagent"}
ROW_STATUSES = {"planned", "scaffolded", "implemented", "verified"}
EVIDENCE_STATUSES = {"planned", "active", "verified"}
EVIDENCE_KINDS = {"automated", "manual", "matrix"}
VERIFICATION_TYPES = {
    "application",
    "architecture",
    "behavior",
    "contract",
    "documentation",
    "fault",
    "integration",
    "live",
    "manual",
    "matrix",
    "property",
    "review",
    "soak",
}
DISPOSITIONS = {"none", "replace", "delete", "retain"}
T1_REQUIREMENTS = {
    "F93", "F94", "F95", "F96", "F97", "F98",
    "N1", "N2", "N3", "N4", "N7", "N13", "N15", "N16",
    "AC22", "AC23", "AC24", "AC25",
}
ALL_REQUIREMENTS = (
    {f"F{number}" for number in range(1, 99)}
    | {f"N{number}" for number in range(1, 17)}
    | {f"AC{number}" for number in range(1, 26)}
)


class MatrixError(ValueError):
    pass


def _mapping(value: Any, location: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise MatrixError(f"{location} 必须是映射。")
    return value


def _list(value: Any, location: str) -> list[Any]:
    if not isinstance(value, list):
        raise MatrixError(f"{location} 必须是列表。")
    return value


def _task_number(task: str) -> int:
    return int(task[1:])


def _validate_task_graph(raw: Any) -> dict[str, list[str]]:
    graph = dict(_mapping(raw, "task_graph"))
    expected = {f"T{number}" for number in range(1, 16)}
    if set(graph) != expected:
        raise MatrixError(f"task_graph 必须精确包含 T1～T15；当前差异：{sorted(set(graph) ^ expected)}")
    for task, dependencies in graph.items():
        if not TASK_PATTERN.fullmatch(task):
            raise MatrixError(f"无效任务编号：{task}")
        deps = _list(dependencies, f"task_graph.{task}")
        if len(deps) != len(set(deps)):
            raise MatrixError(f"{task} 包含重复依赖。")
        unknown = set(deps) - expected
        if unknown:
            raise MatrixError(f"{task} 包含无效依赖：{sorted(unknown)}")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(task: str) -> None:
        if task in visiting:
            raise MatrixError(f"任务依赖存在循环，涉及 {task}。")
        if task in visited:
            return
        visiting.add(task)
        for dependency in graph[task]:
            visit(dependency)
        visiting.remove(task)
        visited.add(task)

    for task in graph:
        visit(task)
    return graph


def _validate_path(path_text: Any, *, status: str, task: str, stage: str) -> None:
    if not isinstance(path_text, str) or not path_text:
        raise MatrixError("验收路径必须是非空字符串。")
    path = PurePosixPath(path_text)
    if path.is_absolute() or ".." in path.parts:
        raise MatrixError(f"验收路径必须是仓库内相对路径：{path_text}")
    allowed_roots = {"tests", "docs", "README.md", "CONTEXT.md", "checklist.md"}
    if path.parts[0] not in allowed_roots:
        raise MatrixError(f"验收路径不在允许位置：{path_text}")
    if path.suffix not in {".py", ".yml", ".yaml", ".md"}:
        raise MatrixError(f"验收路径类型无效：{path_text}")
    exists = (ROOT / path).is_file()
    if status in {"active", "verified"} and not exists:
        raise MatrixError(f"活动验收路径不存在：{path_text}")
    if status == "planned" and _task_number(task) <= _task_number(stage) and not exists:
        raise MatrixError(f"{task} 已到执行阶段，但计划验收路径仍不存在：{path_text}")


def validate_matrix(document: Any, *, stage: str) -> int:
    root = _mapping(document, "matrix")
    if root.get("schema_version") != 1:
        raise MatrixError("schema_version 必须为 1。")
    graph = _validate_task_graph(root.get("task_graph"))
    if stage not in graph:
        raise MatrixError(f"未知验证阶段：{stage}")

    rows = _list(root.get("requirements"), "requirements")
    seen: set[str] = set()
    incomplete_due: list[str] = []
    undeleted_legacy: list[str] = []
    for index, raw_row in enumerate(rows):
        row = _mapping(raw_row, f"requirements[{index}]")
        required_fields = {
            "id", "owner", "implementation_task", "status", "acceptance",
            "verification_types", "legacy_tests", "legacy_disposition",
        }
        missing = required_fields - set(row)
        unknown = set(row) - required_fields
        if missing or unknown:
            raise MatrixError(
                f"requirements[{index}] 字段不符；缺少 {sorted(missing)}，未知 {sorted(unknown)}"
            )
        requirement_id = row["id"]
        if not isinstance(requirement_id, str) or not REQUIREMENT_PATTERN.fullmatch(requirement_id):
            raise MatrixError(f"无效需求编号：{requirement_id}")
        if requirement_id in seen:
            raise MatrixError(f"重复需求编号：{requirement_id}")
        seen.add(requirement_id)
        if row["owner"] not in OWNERS:
            raise MatrixError(f"{requirement_id} 的状态所有者无效：{row['owner']}")
        task = row["implementation_task"]
        if task not in graph:
            raise MatrixError(f"{requirement_id} 的实施任务无效：{task}")
        if row["status"] not in ROW_STATUSES:
            raise MatrixError(f"{requirement_id} 的状态无效：{row['status']}")
        due_limit = 12 if stage == "T13" else 14 if stage == "T14" else 15
        if _task_number(stage) >= 13 and _task_number(task) <= due_limit and row["status"] in {"planned", "scaffolded"}:
            incomplete_due.append(f"{requirement_id}({task}:{row['status']})")

        acceptance = _list(row["acceptance"], f"{requirement_id}.acceptance")
        if not acceptance:
            raise MatrixError(f"{requirement_id} 缺少验收路径。")
        for raw_evidence in acceptance:
            evidence = _mapping(raw_evidence, f"{requirement_id}.acceptance[]")
            if set(evidence) != {"path", "kind", "status"}:
                raise MatrixError(f"{requirement_id} 的验收项字段必须为 path/kind/status。")
            if evidence["kind"] not in EVIDENCE_KINDS:
                raise MatrixError(f"{requirement_id} 的验收类型无效：{evidence['kind']}")
            if evidence["status"] not in EVIDENCE_STATUSES:
                raise MatrixError(f"{requirement_id} 的验收状态无效：{evidence['status']}")
            _validate_path(evidence["path"], status=evidence["status"], task=task, stage=stage)

        verification_types = _list(row["verification_types"], f"{requirement_id}.verification_types")
        if not verification_types or set(verification_types) - VERIFICATION_TYPES:
            raise MatrixError(f"{requirement_id} 包含空或无效的验证类型。")

        legacy_tests = _list(row["legacy_tests"], f"{requirement_id}.legacy_tests")
        for legacy_path in legacy_tests:
            if not isinstance(legacy_path, str) or not legacy_path.startswith("tests/"):
                raise MatrixError(f"{requirement_id} 的旧测试路径无效：{legacy_path}")
        disposition = _mapping(row["legacy_disposition"], f"{requirement_id}.legacy_disposition")
        if set(disposition) != {"action", "task"}:
            raise MatrixError(f"{requirement_id} 的旧测试处置必须包含 action/task。")
        if disposition["action"] not in DISPOSITIONS or disposition["task"] not in graph:
            raise MatrixError(f"{requirement_id} 的旧测试处置无效。")
        if legacy_tests and disposition["action"] == "none":
            raise MatrixError(f"{requirement_id} 列出旧测试但没有处置动作。")
        if (
            _task_number(stage) >= _task_number(disposition["task"])
            and disposition["action"] in {"replace", "delete"}
        ):
            undeleted_legacy.extend(
                path for path in legacy_tests if (ROOT / path).exists()
            )

    if stage == "T1" and not T1_REQUIREMENTS.issubset(seen):
        raise MatrixError(f"T1 缺少需求样例：{sorted(T1_REQUIREMENTS - seen)}")
    if _task_number(stage) >= 13 and seen != ALL_REQUIREMENTS:
        raise MatrixError(
            f"完整矩阵必须精确覆盖 139 项；缺少 {sorted(ALL_REQUIREMENTS - seen)}，"
            f"未知 {sorted(seen - ALL_REQUIREMENTS)}"
        )
    if incomplete_due:
        raise MatrixError("T1～T12 仍有未完成矩阵行：" + ", ".join(incomplete_due))
    if undeleted_legacy:
        raise MatrixError("已到处置任务但旧私有测试仍存在：" + ", ".join(sorted(set(undeleted_legacy))))
    return len(rows)


def load_matrix(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise MatrixError(f"无法读取行为矩阵 {path}: {exc}") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True, choices=[f"T{number}" for number in range(1, 16)])
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        count = validate_matrix(load_matrix(args.matrix), stage=args.stage)
    except MatrixError as exc:
        print(f"ch14 matrix invalid: {exc}", file=sys.stderr)
        return 1
    print(f"ch14 matrix valid for {args.stage}: {count} requirement rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
