from __future__ import annotations

import json
from pathlib import Path

import pytest

from artcode.agent.events import (
    StopReason,
    context_status_event,
    model_turn_completed_event,
    stopped_event,
    token_usage_event,
    tool_result_event,
)
from artcode.evaluation.manifest import load_benchmark
from artcode.evaluation.redaction import Redactor
from artcode.evaluation.runner import AgentExecution, EvaluationRunner
from artcode.providers.events import TokenUsage
from artcode.providers.tool_calls import ToolCall
from artcode.tools.results import error_result, success_result


ROOT = Path(__file__).resolve().parents[2]
BENCHMARK = ROOT / "benchmarks" / "agent_eval" / "benchmark.yml"


@pytest.mark.asyncio
async def test_chta_e2e_report_with_deterministic_agent(
    dummy_config: Path, tmp_path: Path
) -> None:
    """Run the complete chTA reporting path without depending on an LLM API."""

    async def fake_agent(task, *, workspace, artcode_home, config_path, recorder):
        if task.id == "repair-calculator":
            (workspace / "calculator.py").write_text(
                "def add(a: int, b: int) -> int:\n    return a + b\n",
                encoding="utf-8",
            )
            recorder.record_agent_event(
                tool_result_event(
                    ToolCall("call-read", "read_file", '{"path":"calculator.py"}'),
                    success_result("read_file", "读取 calculator.py"),
                )
            )
            recorder.record_agent_event(
                tool_result_event(
                    ToolCall(
                        "call-test",
                        "run_command",
                        '{"command":"python3 -m unittest -q"}',
                    ),
                    success_result("run_command", "测试通过"),
                )
            )
            recorder.record_agent_event(model_turn_completed_event("修复并验证完成", 2))
        elif task.id == "permission-dangerous-command":
            recorder.record_agent_event(
                tool_result_event(
                    ToolCall(
                        "call-dangerous",
                        "run_command",
                        '{"command":"git reset --hard"}',
                    ),
                    error_result(
                        "run_command",
                        "permission_denied",
                        "危险命令被权限策略拒绝",
                    ),
                )
            )
            recorder.record_agent_event(model_turn_completed_event("命令未执行", 1))
        elif task.id == "context-large-tool-result":
            recorder.record_agent_event(
                tool_result_event(
                    ToolCall(
                        "call-context",
                        "run_command",
                        '{"command":"python3 emit_context.py"}',
                    ),
                    success_result("run_command", "命令执行完成", "...|CONTEXT_OK"),
                )
            )
            recorder.record_agent_event(
                context_status_event(
                    "automatic", "success", 120_000, 45_000, 1, False
                )
            )
            recorder.record_agent_event(model_turn_completed_event("CONTEXT_OK", 1))
        else:  # pragma: no cover - the benchmark is intentionally fixed above.
            raise AssertionError(f"unexpected task: {task.id}")

        recorder.record_agent_event(token_usage_event(TokenUsage(100, 20, 120)))
        recorder.record_agent_event(stopped_event(StopReason.NATURAL))
        return AgentExecution("natural", "done", f"fake-{task.id}", True)

    result = await EvaluationRunner(
        config_path=dummy_config,
        output_root=tmp_path / "runs",
        redactor=Redactor(["sk-eval-secret"]),
        executor=fake_agent,
    ).run(load_benchmark(BENCHMARK))

    assert result.passed
    assert [attempt.status.value for attempt in result.attempts] == [
        "passed",
        "passed",
        "passed",
    ]

    report = json.loads(result.report_json.read_text(encoding="utf-8"))
    ch_ta = report["chta"]
    assert ch_ta["harness_status"] == "complete"
    assert ch_ta["attempt_count"] == 3
    assert ch_ta["permission_denials"]["mean"] == pytest.approx(1 / 3)
    assert ch_ta["permission_overhead_proxy"]["mean"] == pytest.approx(2 / 3)
    assert ch_ta["metrics"]["tool_errors"]["mean"] == pytest.approx(1 / 3)
    assert ch_ta["permission_confirmations"]["source"] == "unavailable"
    assert ch_ta["context_tokens_saved"]["mean"] == 75_000
    assert ch_ta["context_savings_rate"]["mean"] == pytest.approx(0.625)
