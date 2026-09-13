from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from artcode.agent import NORMAL_AGENT_MODE
from artcode.evaluation.redaction import Redactor
from artcode.evaluation.trace import RunTraceRecorder
from artcode.permissions import (
    ApprovalChoice,
    PermissionEngine,
    PermissionMode,
    PermissionState,
    RuleLoader,
    RulePaths,
    RuleWriter,
    ShellPolicy,
)
from artcode.permissions.service import PermissionService
from artcode.providers.tool_calls import ToolCall
from artcode.security import DangerousCommandValidator
from artcode.tools import ToolEnvironment, create_default_tool_registry
from artcode.tools.execution import ToolExecutionService


@dataclass(frozen=True)
class PermissionOperation:
    id: str
    tool_name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class PermissionOperationSet:
    repeats_per_target: int
    targets: tuple[PermissionOperation, ...]
    negative_controls: tuple[PermissionOperation, ...]


@dataclass(frozen=True)
class PermissionProfileResult:
    profile: str
    normal_operation_count: int
    completed_operations: int
    approval_requests: int
    allow_once: int
    allow_always: int
    rule_writes: int
    rule_hits: int
    denials: int
    false_allows: int
    false_denials: int
    duration_ms: int
    evidence_path: str


@dataclass(frozen=True)
class PermissionExperimentResult:
    status: str
    baseline: PermissionProfileResult
    candidate: PermissionProfileResult
    approval_reduction_rate: float | None


class ScriptedApprover:
    def __init__(self, profile: str) -> None:
        if profile not in {"once", "always"}:
            raise ValueError("permission profile 必须是 once 或 always")
        self.profile = profile
        self.normal_phase = True

    async def request_approval(self, request):
        if not self.normal_phase:
            return ApprovalChoice.DENY_ONCE
        return (
            ApprovalChoice.ALLOW_ONCE
            if self.profile == "once"
            else ApprovalChoice.ALLOW_ALWAYS
        )

    async def request_mcp_approval(self, preview, plan_mode: bool) -> bool:
        return False


class PermissionExperimentRunner:
    def __init__(
        self,
        operations: PermissionOperationSet,
        *,
        output_dir: Path,
        redactor: Redactor | None = None,
    ) -> None:
        if len(operations.targets) != 5 or operations.repeats_per_target != 6:
            raise ValueError("权限实验必须包含 5 个目标且每个重复 6 次")
        if len({item.id for item in operations.targets}) != len(operations.targets):
            raise ValueError("权限实验目标 ID 不能重复")
        self.operations = operations
        self.output_dir = output_dir
        self.redactor = redactor or Redactor()

    async def run(self) -> PermissionExperimentResult:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        baseline = await self._run_profile("once")
        candidate = await self._run_profile("always")
        reduction = (
            (baseline.approval_requests - candidate.approval_requests)
            / baseline.approval_requests
            if baseline.approval_requests > 0
            else None
        )
        expected = (
            baseline.approval_requests == 30
            and candidate.approval_requests == 5
            and candidate.rule_hits == 25
            and baseline.false_allows == candidate.false_allows == 0
            and baseline.false_denials == candidate.false_denials == 0
        )
        return PermissionExperimentResult(
            "complete" if expected else "failed",
            baseline,
            candidate,
            reduction,
        )

    async def _run_profile(self, profile: str) -> PermissionProfileResult:
        started = time.monotonic()
        root = self.output_dir / profile
        workspace = root / "workspace"
        workspace.mkdir(parents=True, exist_ok=False)
        trace_path = root / "permission-events.jsonl"
        recorder = RunTraceRecorder(
            trace_path,
            run_id=f"permission-{profile}",
            task_id="fixed-side-effect-replay",
            attempt=1,
            redactor=self.redactor,
        )
        recorder.start({"profile": profile})
        state = PermissionState(
            mode=PermissionMode.DEFAULT,
            shell_policy=ShellPolicy.UNSANDBOXED_ASK,
        )
        registry = create_default_tool_registry()
        environment = ToolEnvironment.from_workspace(workspace)
        rules = RuleLoader(
            RulePaths(
                root / "user-permissions.yml",
                root / "project-permissions.yml",
                root / "local-permissions.yml",
            )
        )
        approver = ScriptedApprover(profile)
        permission = PermissionService(
            state,
            engine=PermissionEngine(rules, DangerousCommandValidator.load()),
            approver=approver,
            rule_writer=RuleWriter(rules),
            audit_sink=recorder.record_agent_event,
        )
        executor = ToolExecutionService(registry, environment, permission)

        normal_results = []
        for repetition in range(1, self.operations.repeats_per_target + 1):
            for operation in self.operations.targets:
                arguments = _format_arguments(operation.arguments, repetition)
                normal_results.append(
                    await _execute_operation(
                        executor,
                        recorder,
                        operation.id,
                        operation.tool_name,
                        arguments,
                    )
                )
        normal_record_count = len(recorder.records)
        approver.normal_phase = False
        control_results = []
        for operation in self.operations.negative_controls:
            control_results.append(
                await _execute_operation(
                    executor,
                    recorder,
                    operation.id,
                    operation.tool_name,
                    operation.arguments,
                )
            )
        recorder.finish({"profile": profile})

        normal_records = recorder.records[:normal_record_count]
        audit = [record for record in normal_records if record.kind == "permission_audit"]
        approval_choices = [
            record.payload.get("choice")
            for record in audit
            if record.payload.get("event") == "approval_choice"
        ]
        false_denials = sum(not result.ok for result in normal_results)
        false_allows = sum(result.ok for result in control_results)
        return PermissionProfileResult(
            profile=profile,
            normal_operation_count=len(normal_results),
            completed_operations=sum(result.ok for result in normal_results),
            approval_requests=sum(
                record.payload.get("event") == "approval_requested" for record in audit
            ),
            allow_once=approval_choices.count(ApprovalChoice.ALLOW_ONCE.value),
            allow_always=approval_choices.count(ApprovalChoice.ALLOW_ALWAYS.value),
            rule_writes=sum(record.payload.get("event") == "rule_written" for record in audit),
            rule_hits=sum(
                record.payload.get("event") == "decision"
                and record.payload.get("persistent_rule_hit") is True
                for record in audit
            ),
            denials=sum(
                record.kind == "permission_audit"
                and record.payload.get("event") == "denied"
                for record in recorder.records
            ),
            false_allows=false_allows,
            false_denials=false_denials,
            duration_ms=max(0, int((time.monotonic() - started) * 1000)),
            evidence_path=str(trace_path),
        )


async def _execute_operation(
    executor: ToolExecutionService,
    recorder: RunTraceRecorder,
    operation_id: str,
    tool_name: str,
    arguments: dict[str, Any],
):
    call = ToolCall(operation_id, tool_name, json.dumps(arguments, ensure_ascii=False))
    plan = executor.build_plan([call], NORMAL_AGENT_MODE.tool_policy)
    events = [
        event async for event in executor.execute_plan(plan, mode=NORMAL_AGENT_MODE)
    ]
    for event in events:
        recorder.record_agent_event(event)
    return events[-1].payload["result"]


def _format_arguments(arguments: dict[str, Any], repetition: int) -> dict[str, Any]:
    return {
        key: value.format(repetition=repetition) if isinstance(value, str) else value
        for key, value in arguments.items()
    }


def load_permission_operations(path: Path) -> PermissionOperationSet:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ValueError(f"无法读取权限操作清单：{exc}") from exc
    if not isinstance(raw, dict) or set(raw) != {
        "version",
        "repeats_per_target",
        "targets",
        "negative_controls",
    }:
        raise ValueError("权限操作清单字段不完整或包含未知字段")
    if raw["version"] != 1:
        raise ValueError("权限操作清单 version 必须为 1")
    repeats = raw["repeats_per_target"]
    if isinstance(repeats, bool) or not isinstance(repeats, int) or repeats < 1:
        raise ValueError("repeats_per_target 必须是正整数")
    return PermissionOperationSet(
        repeats,
        _parse_operations(raw["targets"], "targets"),
        _parse_operations(raw["negative_controls"], "negative_controls"),
    )


def _parse_operations(raw: Any, label: str) -> tuple[PermissionOperation, ...]:
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"{label} 必须是非空列表")
    result = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict) or set(item) != {"id", "tool", "arguments"}:
            raise ValueError(f"{label}[{index}] 字段不完整或包含未知字段")
        if not isinstance(item["id"], str) or not item["id"]:
            raise ValueError(f"{label}[{index}].id 必须是非空字符串")
        if not isinstance(item["tool"], str) or not item["tool"]:
            raise ValueError(f"{label}[{index}].tool 必须是非空字符串")
        if not isinstance(item["arguments"], dict):
            raise ValueError(f"{label}[{index}].arguments 必须是映射")
        result.append(PermissionOperation(item["id"], item["tool"], dict(item["arguments"])))
    return tuple(result)


__all__ = [
    "PermissionExperimentResult",
    "PermissionExperimentRunner",
    "PermissionOperation",
    "PermissionOperationSet",
    "PermissionProfileResult",
    "load_permission_operations",
]
