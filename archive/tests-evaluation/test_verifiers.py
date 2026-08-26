from __future__ import annotations

from pathlib import Path

import pytest

from artcode.evaluation.models import TraceRecord, VerifierSpec
from artcode.evaluation.redaction import Redactor
from artcode.evaluation.verifiers import run_verifiers


@pytest.mark.asyncio
async def test_file_and_text_verifiers_cover_pass_and_fail(tmp_path: Path) -> None:
    (tmp_path / "hello.txt").write_text("你好 ArtCode", encoding="utf-8")
    specs = (
        VerifierSpec("exists", "file_exists", path="hello.txt"),
        VerifierSpec("absent", "file_absent", path="missing.txt"),
        VerifierSpec("contains", "file_contains", path="hello.txt", text="ArtCode"),
        VerifierSpec("missing-text", "file_contains", path="hello.txt", text="nope"),
    )
    results = await run_verifiers(
        specs,
        workspace=tmp_path,
        trace=(),
        metrics={},
        redactor=Redactor(),
    )
    assert [item.passed for item in results] == [True, True, True, False]


@pytest.mark.asyncio
async def test_command_verifiers_continue_after_failures(tmp_path: Path) -> None:
    specs = (
        VerifierSpec("ok", "command", argv=("python3", "-c", "print('ok')"), timeout_seconds=5),
        VerifierSpec("nonzero", "command", argv=("python3", "-c", "raise SystemExit(3)"), timeout_seconds=5),
        VerifierSpec("missing", "command", argv=("definitely-not-an-executable",), timeout_seconds=5),
        VerifierSpec("still-runs", "file_absent", path="sentinel"),
    )
    results = await run_verifiers(
        specs,
        workspace=tmp_path,
        trace=(),
        metrics={},
        redactor=Redactor(),
    )
    assert len(results) == 4
    assert [item.status for item in results] == ["passed", "failed", "error", "passed"]


@pytest.mark.asyncio
async def test_command_arguments_are_not_shell_interpreted(tmp_path: Path) -> None:
    sentinel = tmp_path / "pwned"
    spec = VerifierSpec(
        "safe",
        "command",
        argv=("python3", "-c", "import sys; print(sys.argv[1])", f"; touch {sentinel}"),
        timeout_seconds=5,
    )
    result = await run_verifiers(
        (spec,), workspace=tmp_path, trace=(), metrics={}, redactor=Redactor()
    )
    assert result[0].passed
    assert not sentinel.exists()


@pytest.mark.asyncio
async def test_command_timeout_is_structured(tmp_path: Path) -> None:
    result = await run_verifiers(
        (
            VerifierSpec(
                "timeout",
                "command",
                argv=("python3", "-c", "import time; time.sleep(2)"),
                timeout_seconds=0.05,
            ),
        ),
        workspace=tmp_path,
        trace=(),
        metrics={},
        redactor=Redactor(),
    )
    assert result[0].status == "timeout"
    assert not result[0].passed


@pytest.mark.asyncio
async def test_trace_and_metric_verifiers(tmp_path: Path) -> None:
    trace = (
        TraceRecord(
            1,
            "run",
            "task",
            1,
            1,
            0,
            "tool_result",
            {"tool_name": "run_command", "error_code": "permission_denied"},
        ),
        TraceRecord(
            1,
            "run",
            "task",
            1,
            2,
            1,
            "evaluation_invariant",
            {"current_request_preserved": True},
        ),
    )
    specs = (
        VerifierSpec(
            "trace",
            "trace_contains",
            event="tool_result",
            tool_name="run_command",
            error_code="permission_denied",
        ),
        VerifierSpec(
            "invariant",
            "trace_contains",
            event="evaluation_invariant",
            current_request_preserved=True,
        ),
        VerifierSpec("metric", "metric_threshold", metric="tool_calls", operator="ge", value=1),
    )
    results = await run_verifiers(
        specs,
        workspace=tmp_path,
        trace=trace,
        metrics={"tool_calls": 1},
        redactor=Redactor(),
    )
    assert all(item.passed for item in results)


@pytest.mark.asyncio
@pytest.mark.parametrize("operator", ["eq", "ne", "lt", "le", "gt", "ge"])
async def test_metric_operators(operator: str, tmp_path: Path) -> None:
    expected = {"eq": 2, "ne": 3, "lt": 3, "le": 2, "gt": 1, "ge": 2}[operator]
    result = await run_verifiers(
        (VerifierSpec("m", "metric_threshold", metric="x", operator=operator, value=expected),),
        workspace=tmp_path,
        trace=(),
        metrics={"x": 2},
        redactor=Redactor(),
    )
    assert result[0].passed
