from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest
import yaml

from artcode.evaluation.manifest import load_benchmark
from artcode.evaluation.redaction import Redactor
from artcode.evaluation.runner import EvaluationRunner
from tests.live.conftest import load_live_config


pytestmark = [pytest.mark.live]

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.asyncio
async def test_real_deepseek_evaluation_covers_coding_permission_and_context(
    tmp_path: Path,
) -> None:
    if sys.platform != "darwin" or shutil.which("sandbox-exec") is None:
        pytest.skip("environment blocked: production Eval requires macOS sandbox-exec")
    config = load_live_config()
    config_path = tmp_path / "config.yml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "protocol": config.protocol,
                "model": config.model,
                "base_url": config.base_url,
                "api_key": config.api_key,
                "thinking": {"enabled": False},
                "context": {"window_tokens": 200_000},
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    benchmark = load_benchmark(ROOT / "benchmarks" / "agent_eval" / "benchmark.yml")
    result = await EvaluationRunner(
        config_path=config_path,
        output_root=tmp_path / "runs",
        redactor=Redactor([config.api_key]),
        repository=ROOT,
        model_info={"model": config.model, "thinking_enabled": False},
    ).run(benchmark)

    assert result.passed
    attempts = {item.task_id: item for item in result.attempts}
    assert attempts["repair-calculator"].metrics.total_tokens.value > 0
    assert attempts["permission-dangerous-command"].metrics.permission_denials.value >= 1
    context = attempts["context-large-tool-result"].metrics
    assert context.context_events.value >= 1
    assert context.context_tokens_saved.value > 0
    assert config.api_key not in result.report_json.read_text(encoding="utf-8")
