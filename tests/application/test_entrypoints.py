from __future__ import annotations

from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]


def test_source_and_console_entrypoints_share_cli_contract() -> None:
    source = subprocess.run(
        (sys.executable, "-m", "artcode", "--help"),
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    console = subprocess.run(
        (str(ROOT / ".venv/bin/artcode"), "--help"),
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert source.returncode == console.returncode == 0
    assert source.stdout == console.stdout
    assert "--workspace" in source.stdout and "--resume" in source.stdout


def test_both_entries_execute_same_new_session_exit_path(tmp_path: Path) -> None:
    config = tmp_path / "config.yml"
    config.write_text(
        "protocol: openai\nmodel: test\nbase_url: https://example.invalid\napi_key: secret\n",
        encoding="utf-8",
    )
    outcomes = []
    for name, executable in (
        ("source", (sys.executable, "-m", "artcode")),
        ("console", (str(ROOT / ".venv/bin/artcode"),)),
    ):
        workspace = tmp_path / name
        home = tmp_path / f"{name}-home"
        workspace.mkdir()
        home.mkdir()
        result = subprocess.run(
            (
                *executable,
                "--workspace", str(workspace),
                "--artcode-home", str(home),
                "--config", str(config),
                "--new",
            ),
            cwd=ROOT,
            input="/exit\n",
            capture_output=True,
            text=True,
            timeout=10,
        )
        archives = tuple(workspace.glob(".artcode/ch14/sessions/*/transcript.jsonl"))
        outcomes.append((result.returncode, len(archives), archives[0].read_bytes() if archives else None))

    assert outcomes == [(0, 1, b""), (0, 1, b"")]
