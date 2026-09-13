from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .models import (
    BenchmarkSpec,
    BenchmarkTask,
    ChTABudget,
    ChTAExperiment,
    ChTAExperimentKind,
    ChTAManifest,
    ChTAModelSpec,
    ChTAProfile,
    ChTARevisions,
    JudgeSpec,
    VerifierSpec,
)
from .workspace import WorkspaceSafetyError, validate_fixture_tree, validate_relative_path


_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_TOP_FIELDS = {"version", "name", "description", "tasks"}
_TASK_FIELDS = {
    "id",
    "prompt",
    "fixture",
    "repetitions",
    "timeout_seconds",
    "max_iterations",
    "permission_mode",
    "shell_policy",
    "mode",
    "tags",
    "verifiers",
    "judge",
}
_VERIFIER_FIELDS = {
    "id",
    "type",
    "required",
    "path",
    "text",
    "argv",
    "timeout_seconds",
    "event",
    "tool_name",
    "error_code",
    "context_status",
    "current_request_preserved",
    "metric",
    "operator",
    "value",
}
_JUDGE_FIELDS = {"rubric", "minimum_score"}
_VERIFIER_TYPES = {
    "file_exists",
    "file_absent",
    "file_contains",
    "command",
    "trace_contains",
    "metric_threshold",
}
_METRIC_OPERATORS = {"eq", "ne", "lt", "le", "gt", "ge"}
_METRICS = {
    "model_turns",
    "tool_calls",
    "tool_errors",
    "repeated_tool_calls",
    "permission_denials",
    "permission_overhead_proxy",
    "context_events",
    "context_before_tokens",
    "context_after_tokens",
    "context_tokens_saved",
    "context_savings_rate",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "duration_ms",
}

_CHTA_TOP_FIELDS = {
    "version",
    "name",
    "model",
    "budget",
    "revisions",
    "experiments",
}
_CHTA_MODEL_FIELDS = {"provider", "name"}
_CHTA_BUDGET_FIELDS = {"max_iterations", "max_output_tokens", "timeout_seconds"}
_CHTA_REVISION_FIELDS = {
    "swebench_repository",
    "swebench_revision",
    "dataset",
    "dataset_revision",
    "split",
    "baseline_commit",
    "candidate_commit",
}
_CHTA_EXPERIMENT_FIELDS = {
    "id",
    "kind",
    "baseline",
    "candidate",
    "repetitions",
    "tasks",
    "parameters",
}
_CHTA_PROFILE_FIELDS = {"id", "mechanism"}
_CHTA_PARAMETER_FIELDS = {
    "mcp": {"tool_count", "tokenizer", "target_task_count"},
    "permission": {"target_count", "repeats_per_target", "negative_controls"},
    "swebench": {
        "language",
        "sample_size",
        "gold_repetitions",
        "seed",
        "candidate_limit",
    },
}
_SHA = re.compile(r"^[0-9a-f]{40}$")


class BenchmarkValidationError(ValueError):
    def __init__(self, errors: list[str] | tuple[str, ...]) -> None:
        self.errors = tuple(errors)
        super().__init__("Benchmark 校验失败：\n- " + "\n- ".join(self.errors))


@dataclass
class _Validation:
    errors: list[str]

    def add(self, message: str) -> None:
        self.errors.append(message)


def load_benchmark(path: str | Path) -> BenchmarkSpec:
    candidate = Path(path).expanduser()
    if candidate.is_symlink():
        raise BenchmarkValidationError([f"Benchmark 不能是符号链接：{candidate}"])
    source = candidate.resolve(strict=True)
    if not source.is_file():
        raise BenchmarkValidationError([f"Benchmark 必须是普通文件：{source}"])
    try:
        raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise BenchmarkValidationError([f"无法读取 YAML：{exc}"]) from exc
    validation = _Validation([])
    if not isinstance(raw, dict):
        raise BenchmarkValidationError(["顶层必须是映射"])
    _reject_unknown(raw, _TOP_FIELDS, "benchmark", validation)

    version = raw.get("version")
    if version != 1:
        validation.add("version 必须为 1")
    name = _required_text(raw.get("name"), "name", validation)
    description = _optional_text(raw.get("description", ""), "description", validation)
    task_items = raw.get("tasks")
    if not isinstance(task_items, list) or not task_items:
        validation.add("tasks 必须是非空列表")
        task_items = []

    seen_tasks: set[str] = set()
    tasks: list[BenchmarkTask] = []
    for index, item in enumerate(task_items):
        task = _parse_task(item, index, source.parent, seen_tasks, validation)
        if task is not None:
            tasks.append(task)
    if validation.errors:
        raise BenchmarkValidationError(validation.errors)

    canonical = _canonical_manifest(raw)
    fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return BenchmarkSpec(
        version=1,
        name=name,
        description=description,
        source=source,
        fingerprint=fingerprint,
        tasks=tuple(tasks),
    )


def load_chta_manifest(path: str | Path) -> ChTAManifest:
    """Load the strict, comparable chTA experiment manifest."""

    candidate = Path(path).expanduser()
    if candidate.is_symlink():
        raise BenchmarkValidationError([f"chTA 清单不能是符号链接：{candidate}"])
    source = candidate.resolve(strict=True)
    if not source.is_file():
        raise BenchmarkValidationError([f"chTA 清单必须是普通文件：{source}"])
    try:
        raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise BenchmarkValidationError([f"无法读取 chTA YAML：{exc}"]) from exc
    if not isinstance(raw, dict):
        raise BenchmarkValidationError(["chTA 顶层必须是映射"])

    validation = _Validation([])
    _reject_unknown(raw, _CHTA_TOP_FIELDS, "chTA", validation)
    version = raw.get("version")
    if version != 1:
        validation.add("chTA.version 必须为 1")
    name = _required_text(raw.get("name"), "chTA.name", validation)
    model = _parse_chta_model(raw.get("model"), validation)
    budget = _parse_chta_budget(raw.get("budget"), validation)
    revisions = _parse_chta_revisions(raw.get("revisions"), validation)

    experiment_items = raw.get("experiments")
    if not isinstance(experiment_items, list) or not experiment_items:
        validation.add("chTA.experiments 必须是非空列表")
        experiment_items = []
    experiments: list[ChTAExperiment] = []
    seen: set[str] = set()
    seen_kinds: set[str] = set()
    for index, item in enumerate(experiment_items):
        experiment = _parse_chta_experiment(item, index, seen, validation)
        if experiment is not None:
            experiments.append(experiment)
            seen_kinds.add(experiment.kind.value)
    missing = sorted(set(_CHTA_PARAMETER_FIELDS) - seen_kinds)
    if missing:
        validation.add(f"chTA.experiments 缺少实验类型：{', '.join(missing)}")
    if validation.errors:
        raise BenchmarkValidationError(validation.errors)

    fingerprint = hashlib.sha256(
        _canonical_manifest(raw).encode("utf-8")
    ).hexdigest()
    return ChTAManifest(
        version=1,
        name=name,
        source=source,
        fingerprint=fingerprint,
        model=model,
        budget=budget,
        revisions=revisions,
        experiments=tuple(experiments),
    )


def _parse_chta_model(raw: Any, validation: _Validation) -> ChTAModelSpec:
    label = "chTA.model"
    if not isinstance(raw, dict):
        validation.add(f"{label} 必须是映射")
        raw = {}
    _reject_unknown(raw, _CHTA_MODEL_FIELDS, label, validation)
    return ChTAModelSpec(
        provider=_identifier(raw.get("provider"), f"{label}.provider", validation),
        name=_required_text(raw.get("name"), f"{label}.name", validation),
    )


def _parse_chta_budget(raw: Any, validation: _Validation) -> ChTABudget:
    label = "chTA.budget"
    if not isinstance(raw, dict):
        validation.add(f"{label} 必须是映射")
        raw = {}
    _reject_unknown(raw, _CHTA_BUDGET_FIELDS, label, validation)
    return ChTABudget(
        max_iterations=_bounded_int(
            raw.get("max_iterations"), 1, 100, f"{label}.max_iterations", validation
        ),
        max_output_tokens=_bounded_int(
            raw.get("max_output_tokens"),
            1,
            131072,
            f"{label}.max_output_tokens",
            validation,
        ),
        timeout_seconds=_bounded_number(
            raw.get("timeout_seconds"),
            1,
            86400,
            f"{label}.timeout_seconds",
            validation,
        ),
    )


def _parse_chta_revisions(raw: Any, validation: _Validation) -> ChTARevisions:
    label = "chTA.revisions"
    if not isinstance(raw, dict):
        validation.add(f"{label} 必须是映射")
        raw = {}
    _reject_unknown(raw, _CHTA_REVISION_FIELDS, label, validation)
    values = {
        field: _required_text(raw.get(field), f"{label}.{field}", validation)
        for field in _CHTA_REVISION_FIELDS
    }
    for field in ("swebench_revision", "dataset_revision", "baseline_commit", "candidate_commit"):
        if values[field] and not _SHA.fullmatch(values[field]):
            validation.add(f"{label}.{field} 必须是完整的 40 位 Git revision")
    if values["baseline_commit"] and values["baseline_commit"] == values["candidate_commit"]:
        validation.add(f"{label} 的 baseline_commit 与 candidate_commit 不能相同")
    if values["swebench_repository"] and not values["swebench_repository"].startswith(
        "https://"
    ):
        validation.add(f"{label}.swebench_repository 必须使用 https URL")
    return ChTARevisions(**values)


def _parse_chta_experiment(
    raw: Any,
    index: int,
    seen: set[str],
    validation: _Validation,
) -> ChTAExperiment | None:
    label = f"chTA.experiments[{index}]"
    if not isinstance(raw, dict):
        validation.add(f"{label} 必须是映射")
        return None
    _reject_unknown(raw, _CHTA_EXPERIMENT_FIELDS, label, validation)
    experiment_id = _identifier(raw.get("id"), f"{label}.id", validation)
    if experiment_id in seen:
        validation.add(f"{label}.id 重复：{experiment_id}")
    seen.add(experiment_id)
    kind_value = _enum(
        raw.get("kind"), set(_CHTA_PARAMETER_FIELDS), f"{label}.kind", validation
    )
    baseline = _parse_chta_profile(raw.get("baseline"), f"{label}.baseline", validation)
    candidate = _parse_chta_profile(raw.get("candidate"), f"{label}.candidate", validation)
    if baseline.id == candidate.id or baseline.mechanism == candidate.mechanism:
        validation.add(f"{label} 的 baseline 与 candidate 必须声明不同 profile 和机制")
    repetitions = _bounded_int(
        raw.get("repetitions"), 1, 20, f"{label}.repetitions", validation
    )
    tasks = _unique_string_list(raw.get("tasks"), f"{label}.tasks", validation)
    if not tasks:
        validation.add(f"{label}.tasks 不能为空")
    parameters = raw.get("parameters")
    if not isinstance(parameters, dict):
        validation.add(f"{label}.parameters 必须是映射")
        parameters = {}
    _reject_unknown(
        parameters,
        _CHTA_PARAMETER_FIELDS.get(kind_value, set()),
        f"{label}.parameters",
        validation,
    )
    _validate_chta_parameters(kind_value, parameters, f"{label}.parameters", validation)
    return ChTAExperiment(
        id=experiment_id,
        kind=ChTAExperimentKind(kind_value),
        baseline=baseline,
        candidate=candidate,
        repetitions=repetitions,
        tasks=tasks,
        parameters=dict(parameters),
    )


def _parse_chta_profile(
    raw: Any, label: str, validation: _Validation
) -> ChTAProfile:
    if not isinstance(raw, dict):
        validation.add(f"{label} 必须是映射")
        raw = {}
    _reject_unknown(raw, _CHTA_PROFILE_FIELDS, label, validation)
    return ChTAProfile(
        id=_identifier(raw.get("id"), f"{label}.id", validation),
        mechanism=_required_text(raw.get("mechanism"), f"{label}.mechanism", validation),
    )


def _validate_chta_parameters(
    kind: str,
    raw: dict[str, Any],
    label: str,
    validation: _Validation,
) -> None:
    if kind == "mcp":
        _bounded_int(raw.get("tool_count"), 100, 1000, f"{label}.tool_count", validation)
        _bounded_int(
            raw.get("target_task_count"), 1, 100, f"{label}.target_task_count", validation
        )
        _required_text(raw.get("tokenizer"), f"{label}.tokenizer", validation)
    elif kind == "permission":
        _bounded_int(raw.get("target_count"), 1, 100, f"{label}.target_count", validation)
        _bounded_int(
            raw.get("repeats_per_target"),
            2,
            100,
            f"{label}.repeats_per_target",
            validation,
        )
        controls = _unique_string_list(
            raw.get("negative_controls"), f"{label}.negative_controls", validation
        )
        if not controls:
            validation.add(f"{label}.negative_controls 不能为空")
    elif kind == "swebench":
        _required_text(raw.get("language"), f"{label}.language", validation)
        _bounded_int(raw.get("sample_size"), 1, 100, f"{label}.sample_size", validation)
        _bounded_int(
            raw.get("gold_repetitions"), 1, 10, f"{label}.gold_repetitions", validation
        )
        _bounded_int(raw.get("seed"), 0, 2**31 - 1, f"{label}.seed", validation)
        _bounded_int(
            raw.get("candidate_limit"), 1, 10000, f"{label}.candidate_limit", validation
        )


def _unique_string_list(
    value: Any, label: str, validation: _Validation
) -> tuple[str, ...]:
    result = _string_list(value, label, validation)
    if len(set(result)) != len(result):
        validation.add(f"{label} 不能包含重复值")
    return result


def _parse_task(
    raw: Any,
    index: int,
    benchmark_dir: Path,
    seen: set[str],
    validation: _Validation,
) -> BenchmarkTask | None:
    label = f"tasks[{index}]"
    if not isinstance(raw, dict):
        validation.add(f"{label} 必须是映射")
        return None
    _reject_unknown(raw, _TASK_FIELDS, label, validation)
    task_id = _identifier(raw.get("id"), f"{label}.id", validation)
    if task_id in seen:
        validation.add(f"{label}.id 重复：{task_id}")
    seen.add(task_id)
    prompt = _required_text(raw.get("prompt"), f"{label}.prompt", validation)

    fixture_value = raw.get("fixture")
    fixture = benchmark_dir
    if not isinstance(fixture_value, str):
        validation.add(f"{label}.fixture 必须是相对路径")
    else:
        try:
            relative = validate_relative_path(fixture_value, label=f"{label}.fixture")
            fixture = validate_fixture_tree(
                benchmark_dir.joinpath(*relative.parts), benchmark_dir
            )
        except (WorkspaceSafetyError, FileNotFoundError) as exc:
            validation.add(str(exc))

    repetitions = _bounded_int(raw.get("repetitions", 1), 1, 10, f"{label}.repetitions", validation)
    timeout = _bounded_number(raw.get("timeout_seconds", 180), 1, 1800, f"{label}.timeout_seconds", validation)
    max_iterations = _bounded_int(raw.get("max_iterations", 16), 1, 100, f"{label}.max_iterations", validation)
    permission_mode = _enum(raw.get("permission_mode", "full"), {"default", "edit", "full"}, f"{label}.permission_mode", validation)
    shell_policy = _enum(raw.get("shell_policy", "auto"), {"auto", "ask", "off"}, f"{label}.shell_policy", validation)
    mode = _enum(raw.get("mode", "normal"), {"normal", "plan", "do"}, f"{label}.mode", validation)
    if permission_mode != "full" or shell_policy != "auto":
        validation.add(f"{label} 无人值守评测必须使用 permission_mode=full 且 shell_policy=auto")
    tags = _string_list(raw.get("tags", []), f"{label}.tags", validation)

    verifier_items = raw.get("verifiers")
    if not isinstance(verifier_items, list) or not verifier_items:
        validation.add(f"{label}.verifiers 必须是非空列表")
        verifier_items = []
    verifier_seen: set[str] = set()
    verifiers: list[VerifierSpec] = []
    for verifier_index, verifier_raw in enumerate(verifier_items):
        verifier = _parse_verifier(
            verifier_raw,
            f"{label}.verifiers[{verifier_index}]",
            verifier_seen,
            validation,
        )
        if verifier is not None:
            verifiers.append(verifier)

    judge = _parse_judge(raw.get("judge"), f"{label}.judge", validation)
    return BenchmarkTask(
        id=task_id,
        prompt=prompt,
        fixture=fixture,
        repetitions=repetitions,
        timeout_seconds=timeout,
        max_iterations=max_iterations,
        permission_mode=permission_mode,
        shell_policy=shell_policy,
        mode=mode,
        tags=tags,
        verifiers=tuple(verifiers),
        judge=judge,
    )


def _parse_verifier(
    raw: Any,
    label: str,
    seen: set[str],
    validation: _Validation,
) -> VerifierSpec | None:
    if not isinstance(raw, dict):
        validation.add(f"{label} 必须是映射")
        return None
    _reject_unknown(raw, _VERIFIER_FIELDS, label, validation)
    verifier_id = _identifier(raw.get("id"), f"{label}.id", validation)
    if verifier_id in seen:
        validation.add(f"{label}.id 重复：{verifier_id}")
    seen.add(verifier_id)
    verifier_type = _enum(raw.get("type"), _VERIFIER_TYPES, f"{label}.type", validation)
    required = raw.get("required", True)
    if not isinstance(required, bool):
        validation.add(f"{label}.required 必须是布尔值")
        required = True

    path = raw.get("path")
    text = raw.get("text")
    argv: tuple[str, ...] = ()
    timeout: float | None = None
    event = raw.get("event")
    tool_name = raw.get("tool_name")
    error_code = raw.get("error_code")
    context_status = raw.get("context_status")
    current_request_preserved = raw.get("current_request_preserved")
    metric = raw.get("metric")
    operator = raw.get("operator")
    value = raw.get("value")

    if verifier_type in {"file_exists", "file_absent", "file_contains"}:
        if isinstance(path, str):
            try:
                validate_relative_path(path, label=f"{label}.path")
            except WorkspaceSafetyError as exc:
                validation.add(str(exc))
        else:
            validation.add(f"{label}.path 必须是相对路径")
            path = None
    if verifier_type == "file_contains" and (not isinstance(text, str) or not text):
        validation.add(f"{label}.text 必须是非空字符串")
        text = None
    if verifier_type == "command":
        raw_argv = raw.get("argv")
        if (
            not isinstance(raw_argv, list)
            or not 1 <= len(raw_argv) <= 32
            or any(not isinstance(part, str) or not part for part in raw_argv)
        ):
            validation.add(f"{label}.argv 必须含 1～32 个非空字符串")
        else:
            argv = tuple(raw_argv)
        timeout = _bounded_number(raw.get("timeout_seconds", 60), 1, 300, f"{label}.timeout_seconds", validation)
    if verifier_type == "trace_contains":
        fields = (event, tool_name, error_code, context_status)
        if not any(isinstance(item, str) and item for item in fields) and not isinstance(current_request_preserved, bool):
            validation.add(f"{label} 至少需要一个 Trace 过滤条件")
        for field_name, field_value in zip(
            ("event", "tool_name", "error_code", "context_status"), fields
        ):
            if field_value is not None and (not isinstance(field_value, str) or not field_value):
                validation.add(f"{label}.{field_name} 必须是非空字符串")
        if current_request_preserved is not None and not isinstance(current_request_preserved, bool):
            validation.add(f"{label}.current_request_preserved 必须是布尔值")
    if verifier_type == "metric_threshold":
        if not isinstance(metric, str) or metric not in _METRICS:
            validation.add(f"{label}.metric 必须是已定义指标")
            metric = None
        operator = _enum(operator, _METRIC_OPERATORS, f"{label}.operator", validation)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            validation.add(f"{label}.value 必须是数字")
            value = None

    return VerifierSpec(
        id=verifier_id,
        type=verifier_type,
        required=required,
        path=path if isinstance(path, str) else None,
        text=text if isinstance(text, str) else None,
        argv=argv,
        timeout_seconds=timeout,
        event=event if isinstance(event, str) else None,
        tool_name=tool_name if isinstance(tool_name, str) else None,
        error_code=error_code if isinstance(error_code, str) else None,
        context_status=context_status if isinstance(context_status, str) else None,
        current_request_preserved=(
            current_request_preserved
            if isinstance(current_request_preserved, bool)
            else None
        ),
        metric=metric if isinstance(metric, str) else None,
        operator=operator if isinstance(operator, str) else None,
        value=value if isinstance(value, (int, float)) and not isinstance(value, bool) else None,
    )


def _parse_judge(raw: Any, label: str, validation: _Validation) -> JudgeSpec | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        validation.add(f"{label} 必须是映射")
        return None
    _reject_unknown(raw, _JUDGE_FIELDS, label, validation)
    rubric = _required_text(raw.get("rubric"), f"{label}.rubric", validation)
    minimum = _bounded_int(raw.get("minimum_score", 70), 0, 100, f"{label}.minimum_score", validation)
    return JudgeSpec(rubric, minimum)


def _reject_unknown(raw: dict[str, Any], allowed: set[str], label: str, validation: _Validation) -> None:
    unknown = sorted(str(key) for key in raw if key not in allowed)
    if unknown:
        validation.add(f"{label} 含未知字段：{', '.join(unknown)}")


def _required_text(value: Any, label: str, validation: _Validation) -> str:
    if not isinstance(value, str) or not value.strip():
        validation.add(f"{label} 必须是非空字符串")
        return ""
    return value.strip()


def _optional_text(value: Any, label: str, validation: _Validation) -> str:
    if not isinstance(value, str):
        validation.add(f"{label} 必须是字符串")
        return ""
    return value.strip()


def _identifier(value: Any, label: str, validation: _Validation) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        validation.add(f"{label} 必须匹配 {_ID.pattern}")
        return "invalid"
    return value


def _bounded_int(value: Any, minimum: int, maximum: int, label: str, validation: _Validation) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        validation.add(f"{label} 必须是 {minimum}～{maximum} 的整数")
        return minimum
    return value


def _bounded_number(value: Any, minimum: float, maximum: float, label: str, validation: _Validation) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not minimum <= float(value) <= maximum:
        validation.add(f"{label} 必须是 {minimum:g}～{maximum:g} 的数字")
        return float(minimum)
    return float(value)


def _enum(value: Any, allowed: set[str], label: str, validation: _Validation) -> str:
    if not isinstance(value, str) or value not in allowed:
        validation.add(f"{label} 必须是：{', '.join(sorted(allowed))}")
        return sorted(allowed)[0]
    return value


def _string_list(value: Any, label: str, validation: _Validation) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        validation.add(f"{label} 必须是字符串列表")
        return ()
    return tuple(value)


def _canonical_manifest(raw: dict[str, Any]) -> str:
    return json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


__all__ = ["BenchmarkValidationError", "load_benchmark", "load_chta_manifest"]
