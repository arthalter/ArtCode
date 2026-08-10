from __future__ import annotations

from pathlib import Path

import pytest

import artcode.bootstrap as bootstrap_module
from artcode.evaluation.models import BenchmarkTask, VerifierSpec
from artcode.evaluation.redaction import Redactor
from artcode.evaluation.runner import execute_production_agent
from artcode.evaluation.trace import RunTraceRecorder
from artcode.providers.events import (
    ContentDelta,
    StreamCompleted,
    ToolCallsCompleted,
    TokenUsage,
    UsageReported,
)
from artcode.providers.tool_calls import ToolCall


class _ScriptedProvider:
    def __init__(self) -> None:
        self.turn = 0
        self.closed = False

    async def stream(self, request):
        self.turn += 1
        if self.turn == 1:
            yield ToolCallsCompleted(
                (
                    ToolCall(
                        "call-write",
                        "write_file",
                        '{"path":"result.txt","content":"ok\\n","overwrite":false}',
                    ),
                )
            )
            yield StreamCompleted("tool_calls")
            return
        yield ContentDelta("完成并验证。")
        yield UsageReported(TokenUsage(100, 20, 120))
        yield StreamCompleted("stop")

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_production_executor_uses_bootstrap_agent_loop(
    monkeypatch,
    tmp_path: Path,
) -> None:
    provider = _ScriptedProvider()
    monkeypatch.setattr(
        bootstrap_module,
        "DeepSeekChatProvider",
        lambda config: provider,
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    dummy_config = tmp_path / "config.yml"
    dummy_config.write_text(
        """\
protocol: openai
model: test-model
base_url: https://example.invalid/v1
api_key: test-key
thinking:
  enabled: false
context:
  window_tokens: 200000
""",
        encoding="utf-8",
    )
    task = BenchmarkTask(
        id="production-flow",
        prompt="创建 result.txt",
        fixture=workspace,
        repetitions=1,
        timeout_seconds=30,
        max_iterations=4,
        permission_mode="full",
        shell_policy="auto",
        mode="normal",
        tags=("coding",),
        verifiers=(VerifierSpec("exists", "file_exists", path="result.txt"),),
    )
    recorder = RunTraceRecorder(
        tmp_path / "trace.jsonl",
        run_id="run",
        task_id=task.id,
        attempt=1,
        redactor=Redactor(),
    )
    recorder.start()
    execution = await execute_production_agent(
        task,
        workspace=workspace,
        artcode_home=home,
        config_path=dummy_config,
        recorder=recorder,
    )
    recorder.finish({"status": "passed"})
    assert execution.stop_reason == "natural"
    assert execution.current_request_preserved is True
    assert (workspace / "result.txt").read_text(encoding="utf-8") == "ok\n"
    assert provider.turn == 2
    assert provider.closed
    assert any(item.kind == "tool_result" for item in recorder.records)
