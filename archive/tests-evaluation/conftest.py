from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def benchmark_file(tmp_path: Path) -> Path:
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "input.txt").write_text("hello\n", encoding="utf-8")
    path = tmp_path / "benchmark.yml"
    path.write_text(
        """\
version: 1
name: test-benchmark
description: deterministic test
tasks:
  - id: task-one
    prompt: Create result.txt
    fixture: fixture
    repetitions: 1
    timeout_seconds: 10
    max_iterations: 4
    permission_mode: full
    shell_policy: auto
    mode: normal
    tags: [coding]
    verifiers:
      - id: result-exists
        type: file_exists
        path: result.txt
""",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def dummy_config(tmp_path: Path) -> Path:
    path = tmp_path / "config.yml"
    path.write_text(
        """\
protocol: openai
model: test-model
base_url: https://example.invalid/v1
api_key: sk-eval-secret
thinking:
  enabled: false
context:
  window_tokens: 200000
""",
        encoding="utf-8",
    )
    return path
