from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .version_runner import VersionWorkspace


@dataclass(frozen=True)
class DriverResult:
    status: str
    output_path: str
    log_path: str
    error: str = ""


class ExternalCompatDriver:
    """Run an external driver against a snapshot without modifying its source."""

    def run(
        self,
        workspace: VersionWorkspace,
        driver: Path,
        payload: dict,
        *,
        label: str | None = None,
        environment: dict[str, str] | None = None,
        timeout_seconds: int = 1800,
    ) -> DriverResult:
        if workspace.source in driver.resolve().parents:
            raise ValueError("兼容驱动必须位于历史源码快照之外")
        run_root = workspace.output / label if label else workspace.output
        run_root.mkdir(parents=True, exist_ok=label is None)
        input_path = run_root / "driver-input.json"
        output_path = run_root / "driver-output.json"
        log_path = run_root / "driver.log"
        input_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        command = [
            str(workspace.environment / "bin" / "python"),
            str(driver.resolve(strict=True)),
            "--source",
            str(workspace.source),
            "--workspace",
            str(workspace.workspace),
            "--artcode-home",
            str(workspace.artcode_home),
            "--input",
            str(input_path),
            "--output",
            str(output_path),
        ]
        completed = subprocess.run(
            command,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            cwd=workspace.output,
            env={**os.environ, **(environment or {})},
        )
        log_path.write_text(
            "STDOUT\n" + completed.stdout + "\nSTDERR\n" + completed.stderr,
            encoding="utf-8",
        )
        status = "complete" if completed.returncode == 0 and output_path.is_file() else "failed"
        return DriverResult(
            status,
            str(output_path),
            str(log_path),
            "" if status == "complete" else f"driver exit={completed.returncode}",
        )


__all__ = ["DriverResult", "ExternalCompatDriver"]
