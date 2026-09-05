from __future__ import annotations

from pathlib import Path
import subprocess


class GitFailure(RuntimeError):
    pass


def run_git(cwd: Path, *args: str, timeout: float = 30.0) -> str:
    try:
        result = subprocess.run(
            ("git", *args), cwd=cwd, check=False,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise GitFailure(f"Git 执行失败：{exc}") from exc
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "未知 Git 错误"
        raise GitFailure(f"git {' '.join(args)}: {detail}")
    return result.stdout


def try_git(cwd: Path, *args: str) -> str | None:
    try:
        return run_git(cwd, *args)
    except GitFailure:
        return None
