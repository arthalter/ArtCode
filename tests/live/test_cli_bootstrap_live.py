from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.bootstrap_fakes import write_config


pytestmark = [pytest.mark.ch10_5, pytest.mark.live]

ROOT = Path(__file__).resolve().parents[2]


def _command(kind: str) -> list[str]:
    if kind == "module":
        return [sys.executable, "-m", "artcode"]
    executable = Path(sys.executable).with_name("artcode")
    if not executable.exists():
        pytest.skip("environment blocked: artcode console script is not installed")
    return [str(executable)]


def _run(kind: str, workspace: Path, config: Path, home: Path, *selection: str):
    environment = os.environ.copy()
    environment["HOME"] = str(home)
    return subprocess.run(
        [
            *_command(kind),
            "--workspace",
            str(workspace),
            "--config",
            str(config),
            *selection,
        ],
        cwd=ROOT,
        env=environment,
        input="/exit\n",
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )


@pytest.mark.parametrize(
    ("entry_kind", "selection"),
    [
        ("console", "new"),
        ("module", "new"),
        ("module", "resume"),
    ],
    ids=("console-new", "module-new", "module-exact-resume"),
)
def test_real_cli_bootstrap_exit_and_resume(
    tmp_path: Path,
    entry_kind: str,
    selection: str,
) -> None:
    if sys.platform != "darwin" or shutil.which("sandbox-exec") is None:
        pytest.skip("environment blocked: real Bootstrap requires macOS sandbox-exec")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    home = tmp_path / "home"
    config = write_config(home)

    if selection == "resume":
        seeded = _run(entry_kind, workspace, config, home, "--new")
        assert seeded.returncode == 0, seeded.stderr
        journals = list((workspace / ".artcode" / "sessions").glob("*.jsonl"))
        assert len(journals) == 1
        arguments = ("--resume", journals[0].stem)
    else:
        arguments = ("--new",)

    completed = _run(entry_kind, workspace, config, home, *arguments)

    assert completed.returncode == 0, completed.stderr
    assert "Traceback" not in completed.stderr
    assert list((workspace / ".artcode" / "context").iterdir()) == []
