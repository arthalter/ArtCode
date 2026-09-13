from __future__ import annotations

import hashlib
import json
import os
import shutil
import shlex
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class VersionWorkspace:
    profile: str
    commit: str
    source: Path
    environment: Path
    artcode_home: Path
    workspace: Path
    output: Path
    context_hashes: dict[str, str]


class VersionIsolationRunner:
    def __init__(
        self,
        repository: Path,
        output_root: Path,
        *,
        runner: CommandRunner = subprocess.run,
    ) -> None:
        self.repository = repository.resolve(strict=True)
        self.output_root = output_root
        self.runner = runner

    def materialize(self, profile: str, commit: str) -> VersionWorkspace:
        return self.materialize_with_options(profile, commit)

    def materialize_with_options(
        self,
        profile: str,
        commit: str,
        *,
        install_dependencies: bool = True,
    ) -> VersionWorkspace:
        resolved = self._resolve_commit(commit)
        root = self.output_root / profile
        if root.exists():
            raise FileExistsError(f"历史版本目录已存在：{root}")
        source = root / "source"
        source.mkdir(parents=True)
        archive = self.runner(
            ["git", "-C", str(self.repository), "archive", "--format=tar", resolved],
            capture_output=True,
        )
        if archive.returncode != 0:
            raise RuntimeError(f"git archive 失败：{_decode(archive.stderr)}")
        extracted = subprocess.run(
            ["tar", "-xf", "-", "-C", str(source)],
            input=archive.stdout,
            capture_output=True,
        )
        if extracted.returncode != 0:
            raise RuntimeError(f"历史版本解包失败：{_decode(extracted.stderr)}")
        environment = root / "venv"
        if install_dependencies:
            pip_command = [
                str(environment / "bin" / "python"),
                "-m",
                "pip",
                "install",
                "--no-cache-dir",
            ]
            index_url = os.environ.get("ARTCODE_PIP_INDEX_URL")
            if index_url:
                if not index_url.startswith("https://"):
                    raise ValueError("ARTCODE_PIP_INDEX_URL 必须使用 https://")
                pip_command.extend(["--index-url", index_url])
            pip_command.extend(["-e", str(source)])
            created = self.runner(
                [sys.executable, "-m", "venv", str(environment)],
                text=True,
                capture_output=True,
            )
            if created.returncode != 0:
                raise RuntimeError(f"历史版本 venv 创建失败：{created.stderr.strip()}")
            installed = self.runner(
                pip_command,
                text=True,
                capture_output=True,
                timeout=900,
            )
            if installed.returncode != 0:
                raise RuntimeError(f"历史版本依赖安装失败：{installed.stderr[-2000:]}")
        else:
            (environment / "bin").mkdir(parents=True)
            python_wrapper = environment / "bin" / "python"
            python_wrapper.write_text(
                "#!/bin/sh\nexec " + shlex.quote(sys.executable) + ' "$@"\n',
                encoding="utf-8",
            )
            python_wrapper.chmod(0o755)
        artcode_home = root / "artcode-home"
        workspace = root / "workspace"
        output = root / "output"
        for path in (artcode_home, workspace, output):
            path.mkdir()
        metadata = {
            "profile": profile,
            "commit": resolved,
            "source": str(source),
            "context_hashes": _hash_tree(source / "artcode" / "context_management"),
            "dependencies_installed": install_dependencies,
        }
        (root / "version-lock.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return VersionWorkspace(
            profile,
            resolved,
            source,
            environment,
            artcode_home,
            workspace,
            output,
            metadata["context_hashes"],
        )

    def assert_context_unchanged(self, workspace: VersionWorkspace) -> None:
        actual = _hash_tree(workspace.source / "artcode" / "context_management")
        if actual != workspace.context_hashes:
            raise RuntimeError(f"{workspace.profile} 的被测上下文源码在运行期间发生变化")

    def _resolve_commit(self, commit: str) -> str:
        completed = self.runner(
            ["git", "-C", str(self.repository), "rev-parse", f"{commit}^{{commit}}"],
            text=True,
            capture_output=True,
        )
        resolved = completed.stdout.strip() if completed.returncode == 0 else ""
        if len(resolved) != 40 or any(char not in "0123456789abcdef" for char in resolved):
            raise ValueError(f"无效历史提交：{commit}")
        return resolved


def _hash_tree(root: Path) -> dict[str, str]:
    if not root.is_dir():
        raise FileNotFoundError(f"被测上下文目录不存在：{root}")
    result: dict[str, str] = {}
    for path in sorted(root.rglob("*.py")):
        result[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    if not result:
        raise ValueError(f"被测上下文目录没有 Python 文件：{root}")
    return result


def _decode(value) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value or "")


__all__ = ["VersionIsolationRunner", "VersionWorkspace"]
