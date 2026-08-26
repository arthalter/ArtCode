from __future__ import annotations

import json
import asyncio
from dataclasses import replace
from pathlib import Path

import pytest

from artcode.agent.events import StopReason, model_turn_completed_event, stopped_event
from artcode.evaluation.cli import main
from artcode.evaluation.manifest import load_benchmark
from artcode.evaluation.redaction import Redactor
from artcode.evaluation.runner import AgentExecution, EvaluationRunner


@pytest.mark.asyncio
async def test_runner_creates_isolated_attempts_and_report(
    benchmark_file: Path,
    dummy_config: Path,
    tmp_path: Path,
) -> None:
    benchmark_file.write_text(
        benchmark_file.read_text(encoding="utf-8").replace(
            "repetitions: 1", "repetitions: 3"
        ),
        encoding="utf-8",
    )
    locations: list[tuple[Path, Path]] = []

    async def fake(task, *, workspace, artcode_home, config_path, recorder):
        locations.append((workspace, artcode_home))
        (workspace / "result.txt").write_text("ok", encoding="utf-8")
        recorder.record_agent_event(model_turn_completed_event("done", 0))
        recorder.record_agent_event(stopped_event(StopReason.NATURAL))
        return AgentExecution("natural", "done", f"session-{len(locations)}", True)

    runner = EvaluationRunner(
        config_path=dummy_config,
        output_root=tmp_path / "runs",
        redactor=Redactor(["sk-eval-secret"]),
        executor=fake,
    )
    result = await runner.run(load_benchmark(benchmark_file))
    assert result.passed
    assert len(result.attempts) == 3
    assert len({str(item[0]) for item in locations}) == 3
    assert len({str(item[1]) for item in locations}) == 3
    assert (benchmark_file.parent / "fixture" / "result.txt").exists() is False
    saved = json.loads(result.report_json.read_text(encoding="utf-8"))
    assert saved["aggregate"]["success_rate"] == 1.0
    assert "sk-eval-secret" not in result.report_json.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_runner_agent_failure_still_runs_verifiers(
    benchmark_file: Path,
    dummy_config: Path,
    tmp_path: Path,
) -> None:
    async def fake(task, *, workspace, artcode_home, config_path, recorder):
        recorder.record_agent_event(stopped_event(StopReason.STREAM_ERROR, "bad"))
        return AgentExecution("stream_error", "", "session", True)

    runner = EvaluationRunner(
        config_path=dummy_config,
        output_root=tmp_path / "runs",
        redactor=Redactor(),
        executor=fake,
    )
    result = await runner.run(load_benchmark(benchmark_file))
    attempt = result.attempts[0]
    assert attempt.status.value == "agent_failed"
    assert len(attempt.verifications) == 1
    assert not attempt.verifications[0].passed


@pytest.mark.asyncio
async def test_runner_timeout_is_recorded(
    benchmark_file: Path,
    dummy_config: Path,
    tmp_path: Path,
) -> None:
    benchmark_file.write_text(
        benchmark_file.read_text(encoding="utf-8").replace(
            "timeout_seconds: 10", "timeout_seconds: 1"
        ),
        encoding="utf-8",
    )

    async def slow(task, *, workspace, artcode_home, config_path, recorder):
        await asyncio.sleep(10)
        return AgentExecution("natural", "late", "session", True)

    result = await EvaluationRunner(
        config_path=dummy_config,
        output_root=tmp_path / "runs",
        redactor=Redactor(),
        executor=slow,
    ).run(load_benchmark(benchmark_file))
    assert result.attempts[0].status.value == "timeout"
    assert result.attempts[0].stop_reason == "timeout"


@pytest.mark.asyncio
async def test_setup_failure_does_not_block_following_task(
    benchmark_file: Path,
    dummy_config: Path,
    tmp_path: Path,
) -> None:
    benchmark = load_benchmark(benchmark_file)
    original = benchmark.tasks[0]
    missing = tmp_path / "missing-fixture"
    broken = replace(original, id="broken", fixture=missing)
    healthy = replace(original, id="healthy")
    benchmark = replace(benchmark, tasks=(broken, healthy))

    async def fake(task, *, workspace, artcode_home, config_path, recorder):
        (workspace / "result.txt").write_text("ok", encoding="utf-8")
        recorder.record_agent_event(stopped_event(StopReason.NATURAL))
        return AgentExecution("natural", "done", "session", True)

    result = await EvaluationRunner(
        config_path=dummy_config,
        output_root=tmp_path / "runs",
        redactor=Redactor(),
        executor=fake,
    ).run(benchmark)
    assert [item.status.value for item in result.attempts] == ["setup_failed", "passed"]


@pytest.mark.asyncio
async def test_cancellation_preserves_partial_trace_and_attempt(
    benchmark_file: Path,
    dummy_config: Path,
    tmp_path: Path,
) -> None:
    entered = asyncio.Event()

    async def waiting(task, *, workspace, artcode_home, config_path, recorder):
        entered.set()
        await asyncio.sleep(10)
        return AgentExecution("natural", "late", "session", True)

    output_root = tmp_path / "runs"
    runner_task = asyncio.create_task(
        EvaluationRunner(
            config_path=dummy_config,
            output_root=output_root,
            redactor=Redactor(),
            executor=waiting,
        ).run(load_benchmark(benchmark_file))
    )
    await entered.wait()
    runner_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await runner_task
    traces = list(output_root.glob("*/traces/task-one/1.jsonl"))
    attempts = list(output_root.glob("*/attempts/task-one/1.json"))
    reports = list(output_root.glob("*/report.json"))
    assert len(traces) == len(attempts) == len(reports) == 1
    assert json.loads(attempts[0].read_text(encoding="utf-8"))["status"] == "cancelled"
    assert json.loads(reports[0].read_text(encoding="utf-8"))["interrupted"] is True


def test_cli_validate_exit_codes(benchmark_file: Path, capsys) -> None:
    assert main(["validate", str(benchmark_file)]) == 0
    assert "sha256=" in capsys.readouterr().out
    benchmark_file.write_text("version: 2\n", encoding="utf-8")
    assert main(["validate", str(benchmark_file)]) == 2


def test_cli_help(capsys) -> None:
    with pytest.raises(SystemExit) as caught:
        main(["--help"])
    assert caught.value.code == 0
    assert "validate" in capsys.readouterr().out
