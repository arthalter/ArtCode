from __future__ import annotations

import asyncio
import os
import signal
import time
from pathlib import Path
from typing import Any, Iterable

from .models import TraceRecord, VerificationResult, VerifierSpec
from .redaction import Redactor
from .workspace import WorkspaceSafetyError, resolve_workspace_path


async def run_verifiers(
    specs: Iterable[VerifierSpec],
    *,
    workspace: Path,
    trace: Iterable[TraceRecord],
    metrics: dict[str, int | float | bool | None],
    redactor: Redactor,
) -> tuple[VerificationResult, ...]:
    records = tuple(trace)
    results: list[VerificationResult] = []
    for spec in specs:
        started = time.monotonic()
        try:
            passed, status, evidence = await _run_one(
                spec,
                workspace=workspace,
                trace=records,
                metrics=metrics,
                redactor=redactor,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            passed, status, evidence = False, "error", str(exc)
        results.append(
            VerificationResult(
                id=spec.id,
                type=spec.type,
                required=spec.required,
                passed=passed,
                status=status,
                duration_ms=max(0, int((time.monotonic() - started) * 1000)),
                evidence=redactor.preview(evidence, limit=4000).text,
            )
        )
    return tuple(results)


async def _run_one(
    spec: VerifierSpec,
    *,
    workspace: Path,
    trace: tuple[TraceRecord, ...],
    metrics: dict[str, int | float | bool | None],
    redactor: Redactor,
) -> tuple[bool, str, str]:
    if spec.type == "file_exists":
        target = resolve_workspace_path(workspace, spec.path or "", must_exist=False)
        passed = target.exists()
        return passed, "passed" if passed else "failed", f"{spec.path}: {'存在' if passed else '不存在'}"
    if spec.type == "file_absent":
        target = resolve_workspace_path(workspace, spec.path or "", must_exist=False)
        passed = not target.exists()
        return passed, "passed" if passed else "failed", f"{spec.path}: {'不存在' if passed else '意外存在'}"
    if spec.type == "file_contains":
        try:
            target = resolve_workspace_path(workspace, spec.path or "", must_exist=True)
        except FileNotFoundError:
            return False, "failed", f"{spec.path}: 文件不存在"
        if not target.is_file():
            return False, "failed", f"{spec.path}: 不是普通文件"
        try:
            content = target.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return False, "failed", f"{spec.path}: 不是合法 UTF-8"
        passed = (spec.text or "") in content
        return passed, "passed" if passed else "failed", f"{spec.path}: {'包含' if passed else '不包含'}目标文本"
    if spec.type == "command":
        return await _run_command(
            spec.argv,
            workspace=workspace,
            timeout=spec.timeout_seconds or 60,
            redactor=redactor,
        )
    if spec.type == "trace_contains":
        matches = [record for record in trace if _trace_matches(record, spec)]
        passed = bool(matches)
        evidence = f"匹配 Trace {len(matches)} 条"
        return passed, "passed" if passed else "failed", evidence
    if spec.type == "metric_threshold":
        actual = metrics.get(spec.metric or "")
        if isinstance(actual, bool) or not isinstance(actual, (int, float)):
            return False, "unavailable", f"指标 {spec.metric} 不可用"
        expected = spec.value
        if expected is None:
            return False, "error", "阈值缺失"
        passed = _compare(actual, spec.operator or "", expected)
        return (
            passed,
            "passed" if passed else "failed",
            f"{spec.metric}={actual} {spec.operator} {expected}",
        )
    return False, "error", f"未知 Verifier：{spec.type}"


async def _run_command(
    argv: tuple[str, ...],
    *,
    workspace: Path,
    timeout: float,
    redactor: Redactor,
) -> tuple[bool, str, str]:
    if not argv:
        return False, "error", "命令 argv 为空"
    try:
        process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=workspace,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
    except (FileNotFoundError, PermissionError, OSError) as exc:
        return False, "error", f"命令无法启动：{exc}"
    try:
        async with asyncio.timeout(timeout):
            stdout, stderr = await process.communicate()
    except TimeoutError:
        await _kill_process_group(process)
        return False, "timeout", f"命令超过 {timeout:g} 秒"
    except asyncio.CancelledError:
        await _kill_process_group(process)
        raise
    output = (stdout + b"\n" + stderr).decode("utf-8", errors="replace")
    preview = redactor.preview(output, limit=4000).text
    passed = process.returncode == 0
    return passed, "passed" if passed else "failed", f"exit={process.returncode}\n{preview}"


async def _kill_process_group(process: asyncio.subprocess.Process) -> None:
    if process.returncode is None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        await process.wait()
    except ProcessLookupError:
        pass


def _trace_matches(record: TraceRecord, spec: VerifierSpec) -> bool:
    if spec.event is not None and record.kind != spec.event:
        return False
    if spec.tool_name is not None and record.payload.get("tool_name") != spec.tool_name:
        return False
    if spec.error_code is not None and record.payload.get("error_code") != spec.error_code:
        return False
    if spec.context_status is not None and record.payload.get("status") != spec.context_status:
        return False
    if (
        spec.current_request_preserved is not None
        and record.payload.get("current_request_preserved")
        is not spec.current_request_preserved
    ):
        return False
    return True


def _compare(actual: float, operator: str, expected: float) -> bool:
    operations = {
        "eq": actual == expected,
        "ne": actual != expected,
        "lt": actual < expected,
        "le": actual <= expected,
        "gt": actual > expected,
        "ge": actual >= expected,
    }
    if operator not in operations:
        raise WorkspaceSafetyError(f"未知比较符：{operator}")
    return operations[operator]


__all__ = ["run_verifiers"]
