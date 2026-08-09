from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from tests.live.conftest import load_live_config


pytestmark = [pytest.mark.ch10_5, pytest.mark.live]

ROOT = Path(__file__).resolve().parents[2]


def _write_live_config(path: Path) -> Path:
    config = load_live_config()
    path.write_text(
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
    return path


def _run(
    workspace: Path,
    home: Path,
    config: Path,
    input_text: str,
    *selection: str,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["HOME"] = str(home)
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "artcode",
            "--workspace",
            str(workspace),
            "--config",
            str(config),
            *selection,
        ],
        cwd=ROOT,
        env=environment,
        input=input_text,
        text=True,
        capture_output=True,
        timeout=180,
        check=False,
    )


def _journal_records(workspace: Path) -> tuple[Path, list[dict]]:
    journals = list((workspace / ".artcode" / "sessions").glob("*.jsonl"))
    assert len(journals) == 1
    records = [json.loads(line) for line in journals[0].read_text(encoding="utf-8").splitlines()]
    return journals[0], records


def test_live_full_entrypoint_persists_real_deepseek_turn(tmp_path: Path) -> None:
    marker = "ARTCODE_LIVE_FINAL_7319"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    config = _write_live_config(home / "config.yml")

    completed = _run(
        workspace,
        home,
        config,
        f"只回复 {marker}，不要添加其他内容。\r/exit\r",
        "--new",
    )

    assert completed.returncode == 0, completed.stderr
    assert marker in completed.stdout
    assert load_live_config().api_key not in completed.stdout + completed.stderr
    _journal, records = _journal_records(workspace)
    assert [record["message"]["role"] for record in records] == ["user", "assistant"]
    assert records[0]["message"]["content"].startswith("只回复")
    assert marker in records[1]["message"]["content"]


def test_live_exact_resume_continues_the_same_real_session(tmp_path: Path) -> None:
    marker = "ARTCODE_LIVE_RESUME_8642"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    config = _write_live_config(home / "config.yml")
    first = _run(
        workspace,
        home,
        config,
        f"记住标记 {marker}，只回复已记住。\r/exit\r",
        "--new",
    )
    assert first.returncode == 0, first.stderr
    journal, before = _journal_records(workspace)

    resumed = _run(
        workspace,
        home,
        config,
        "上一条用户消息里的标记是什么？只回复完整标记。\r/exit\r",
        "--resume",
        journal.stem,
    )

    assert resumed.returncode == 0, resumed.stderr
    assert marker in resumed.stdout
    assert "(restored)" in resumed.stdout
    after = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()]
    assert len(after) == len(before) + 2
    assert [record["message"]["role"] for record in after[-2:]] == ["user", "assistant"]
    assert marker in after[-1]["message"]["content"]
