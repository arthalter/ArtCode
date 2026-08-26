from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import yaml

from artcode.evaluation.models import ChTARevisions


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class SWEbenchLock:
    version: int
    namespace: str
    sample_size: int
    gold_repetitions: int
    seed: int
    candidates: tuple[str, ...]


@dataclass(frozen=True)
class PreflightCheck:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class EnvironmentPreflight:
    status: str
    checks: tuple[PreflightCheck, ...]
    log_path: str


@dataclass(frozen=True)
class OfficialRunResult:
    instance_id: str
    repetition: int
    resolved: bool | None
    status: str
    command: tuple[str, ...]
    report_path: str
    stdout_path: str
    error: str = ""


@dataclass(frozen=True)
class GoldInstanceResult:
    instance_id: str
    valid: bool
    attempts: tuple[OfficialRunResult, ...]
    exclusion_reason: str = ""


@dataclass(frozen=True)
class GoldPreflightResult:
    status: str
    locked_instances: tuple[str, ...]
    instances: tuple[GoldInstanceResult, ...]
    evidence_path: str


def load_swebench_lock(path: Path) -> SWEbenchLock:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ValueError(f"无法读取 SWE-bench-Live lock：{exc}") from exc
    allowed = {
        "version",
        "namespace",
        "sample_size",
        "gold_repetitions",
        "seed",
        "candidates",
    }
    if not isinstance(raw, dict) or set(raw) != allowed:
        raise ValueError("SWE-bench-Live lock 字段不完整或包含未知字段")
    if raw["version"] != 1:
        raise ValueError("SWE-bench-Live lock.version 必须为 1")
    for field in ("sample_size", "gold_repetitions", "seed"):
        value = raw[field]
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"SWE-bench-Live lock.{field} 必须是正整数")
    candidates = raw["candidates"]
    if (
        not isinstance(candidates, list)
        or len(candidates) < raw["sample_size"]
        or any(not isinstance(item, str) or not item for item in candidates)
        or len(set(candidates)) != len(candidates)
    ):
        raise ValueError("SWE-bench-Live lock.candidates 必须是足量且不重复的 ID 列表")
    if not isinstance(raw["namespace"], str) or not raw["namespace"]:
        raise ValueError("SWE-bench-Live lock.namespace 必须是非空字符串")
    return SWEbenchLock(
        1,
        raw["namespace"],
        raw["sample_size"],
        raw["gold_repetitions"],
        raw["seed"],
        tuple(candidates),
    )


def run_environment_preflight(
    output_dir: Path,
    *,
    check_network: bool = True,
    minimum_free_gib: int = 20,
    runner: CommandRunner = subprocess.run,
) -> EnvironmentPreflight:
    output_dir.mkdir(parents=True, exist_ok=True)
    checks: list[PreflightCheck] = []
    checks.append(_command_check("git", ["git", "--version"], runner))
    checks.append(
        _command_check(
            "docker_daemon",
            ["docker", "version", "--format", "{{.Server.Version}}"],
            runner,
        )
    )
    free = shutil.disk_usage(output_dir).free
    checks.append(
        PreflightCheck(
            "disk",
            free >= minimum_free_gib * 1024**3,
            f"free_bytes={free}; minimum_gib={minimum_free_gib}",
        )
    )
    machine = platform.machine().lower()
    checks.append(
        PreflightCheck(
            "architecture",
            machine in {"arm64", "aarch64", "x86_64", "amd64"},
            f"host={machine}; official harness selects per-instance architecture",
        )
    )
    if check_network:
        checks.append(_network_check("official_repository", "https://github.com/microsoft/SWE-bench-Live"))
        checks.append(
            _network_check(
                "official_dataset",
                "https://huggingface.co/datasets/SWE-bench-Live/SWE-bench-Live",
            )
        )
    log_path = output_dir / "environment-preflight.json"
    payload = {
        "status": "ready" if all(item.passed for item in checks) else "blocked",
        "checks": [item.__dict__ for item in checks],
    }
    log_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return EnvironmentPreflight(payload["status"], tuple(checks), str(log_path))


def materialize_official_harness(
    repository_url: str,
    revision: str,
    target: Path,
    *,
    runner: CommandRunner = subprocess.run,
) -> Path:
    if target.exists():
        raise FileExistsError(f"官方 Harness 目标目录已存在：{target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    commands = (
        ["git", "init", str(target)],
        ["git", "-C", str(target), "remote", "add", "origin", repository_url],
        ["git", "-C", str(target), "fetch", "--depth", "1", "origin", revision],
        ["git", "-C", str(target), "checkout", "--detach", "FETCH_HEAD"],
    )
    for command in commands:
        completed = runner(command, text=True, capture_output=True)
        if completed.returncode != 0:
            raise RuntimeError(
                f"官方 Harness materialize 失败：{' '.join(command)}：{completed.stderr.strip()}"
            )
    resolved = runner(
        ["git", "-C", str(target), "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
    )
    if resolved.returncode != 0 or resolved.stdout.strip() != revision:
        raise RuntimeError("官方 Harness checkout revision 与锁定值不一致")
    return target


def install_official_harness(
    repository: Path,
    environment: Path,
    *,
    runner: CommandRunner = subprocess.run,
) -> Path:
    if environment.exists():
        raise FileExistsError(f"官方 Harness 环境已存在：{environment}")
    base_python = os.environ.get("ARTCODE_SWEBENCH_PYTHON", sys.executable)
    completed = runner(
        [base_python, "-m", "venv", "--system-site-packages", str(environment)],
        text=True,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"创建官方 Harness venv 失败：{completed.stderr.strip()}")
    python = environment / "bin" / "python"
    install_command = [
        str(python),
        "-m",
        "pip",
        "install",
        "--no-cache-dir",
        "--no-build-isolation",
    ]
    index_url = os.environ.get("ARTCODE_PIP_INDEX_URL")
    if index_url:
        if not index_url.startswith("https://"):
            raise ValueError("ARTCODE_PIP_INDEX_URL 必须使用 https://")
        install_command.extend(["--index-url", index_url])
    install_command.extend(["-e", str(repository)])
    completed = runner(
        install_command,
        text=True,
        capture_output=True,
        timeout=900,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"安装官方 Harness 失败：{completed.stderr[-2000:]}")
    return python


def materialize_pinned_dataset(
    python: Path,
    revisions: ChTARevisions,
    target: Path,
    *,
    runner: CommandRunner = subprocess.run,
) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    script = (
        "import json,sys\n"
        "from datasets import load_dataset\n"
        "name,revision,split,target=sys.argv[1:]\n"
        "data=load_dataset(name, split=split, revision=revision)\n"
        "open(target,'w',encoding='utf-8').write(json.dumps(data.to_list(),ensure_ascii=False,default=str))\n"
    )
    completed = runner(
        [
            str(python),
            "-c",
            script,
            revisions.dataset,
            revisions.dataset_revision,
            revisions.split,
            str(target),
        ],
        text=True,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"锁定数据集导出失败：{completed.stderr[-2000:]}")
    if not target.is_file() or target.stat().st_size == 0:
        raise RuntimeError("锁定数据集导出后为空")
    return target


class OfficialSWEbenchAdapter:
    def __init__(
        self,
        *,
        python: Path,
        repository: Path,
        dataset_json: Path,
        namespace: str,
        output_dir: Path,
        timeout_seconds: int = 1800,
        runner: CommandRunner = subprocess.run,
    ) -> None:
        self.python = python
        self.repository = repository
        self.dataset_json = dataset_json
        self.namespace = namespace
        self.output_dir = output_dir
        self.timeout_seconds = timeout_seconds
        self.runner = runner

    def run_gold(self, instance_id: str, repetition: int) -> OfficialRunResult:
        attempt_dir = self.output_dir / instance_id / f"gold-{repetition}"
        attempt_dir.mkdir(parents=True, exist_ok=False)
        run_id = f"gold-{instance_id}-{repetition}"
        command = (
            str(self.python),
            "-m",
            "swebench.harness.run_evaluation",
            "--dataset_name",
            str(self.dataset_json),
            "--split",
            "verified",
            "--instance_ids",
            instance_id,
            "--namespace",
            self.namespace,
            "--predictions_path",
            "gold",
            "--max_workers",
            "1",
            "--run_id",
            run_id,
            "--timeout",
            str(self.timeout_seconds),
            "--report_dir",
            str(attempt_dir),
            "--clean",
            "false",
            "--cache_level",
            "instance",
        )
        completed = self.runner(
            list(command),
            cwd=attempt_dir,
            text=True,
            capture_output=True,
            timeout=self.timeout_seconds + 600,
        )
        stdout_path = attempt_dir / "official-command.log"
        stdout_path.write_text(
            "STDOUT\n" + completed.stdout + "\nSTDERR\n" + completed.stderr,
            encoding="utf-8",
        )
        legacy_report_path = (
            attempt_dir
            / "logs"
            / "run_evaluation"
            / run_id
            / "gold"
            / instance_id
            / "report.json"
        )
        summary_report_path = attempt_dir / f"gold.{run_id}.json"
        report_path = (
            summary_report_path
            if summary_report_path.is_file()
            else legacy_report_path
        )
        resolved = _official_resolved(report_path, instance_id)
        status = (
            "resolved"
            if resolved is True
            else "unresolved"
            if resolved is False
            else "failed"
        )
        error = "" if completed.returncode == 0 and resolved is not None else f"exit={completed.returncode}; report={report_path.exists()}"
        return OfficialRunResult(
            instance_id,
            repetition,
            resolved,
            status,
            command,
            str(report_path),
            str(stdout_path),
            error,
        )

    def run_patch(
        self,
        instance_id: str,
        profile: str,
        patch: str,
    ) -> OfficialRunResult:
        attempt_dir = self.output_dir / instance_id / profile
        attempt_dir.mkdir(parents=True, exist_ok=False)
        run_id = f"agent-{profile}-{instance_id}"
        prediction_path = attempt_dir / f"{profile}.json"
        prediction_path.write_text(
            json.dumps(
                [
                    {
                        "instance_id": instance_id,
                        "model_name_or_path": profile,
                        "model_patch": patch,
                    }
                ],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        command = (
            str(self.python),
            "-m",
            "swebench.harness.run_evaluation",
            "--dataset_name",
            str(self.dataset_json),
            "--split",
            "verified",
            "--instance_ids",
            instance_id,
            "--namespace",
            self.namespace,
            "--predictions_path",
            str(prediction_path),
            "--max_workers",
            "1",
            "--run_id",
            run_id,
            "--timeout",
            str(self.timeout_seconds),
            "--report_dir",
            str(attempt_dir),
            "--clean",
            "false",
            "--cache_level",
            "instance",
        )
        completed = self.runner(
            list(command),
            cwd=attempt_dir,
            text=True,
            capture_output=True,
            timeout=self.timeout_seconds + 600,
        )
        stdout_path = attempt_dir / "official-command.log"
        stdout_path.write_text(
            "STDOUT\n" + completed.stdout + "\nSTDERR\n" + completed.stderr,
            encoding="utf-8",
        )
        summaries = tuple(attempt_dir.glob(f"*.{run_id}.json"))
        legacy = (
            attempt_dir
            / "logs"
            / "run_evaluation"
            / run_id
            / profile
            / instance_id
            / "report.json"
        )
        report_path = summaries[0] if summaries else legacy
        resolved = _official_resolved(report_path, instance_id)
        status = (
            "resolved"
            if resolved is True
            else "unresolved"
            if resolved is False
            else "failed"
        )
        error = (
            ""
            if completed.returncode == 0 and resolved is not None
            else f"exit={completed.returncode}; report={report_path.exists()}"
        )
        return OfficialRunResult(
            instance_id,
            1,
            resolved,
            status,
            command,
            str(report_path),
            str(stdout_path),
            error,
        )


def run_gold_preflight(
    adapter: OfficialSWEbenchAdapter,
    lock: SWEbenchLock,
    output_path: Path,
) -> GoldPreflightResult:
    locked: list[str] = []
    results: list[GoldInstanceResult] = []
    for instance_id in lock.candidates:
        attempts = tuple(
            adapter.run_gold(instance_id, repetition)
            for repetition in range(1, lock.gold_repetitions + 1)
        )
        valid = all(attempt.resolved is True for attempt in attempts)
        results.append(
            GoldInstanceResult(
                instance_id,
                valid,
                attempts,
                "" if valid else "gold patch 未连续通过官方验证",
            )
        )
        if valid:
            locked.append(instance_id)
        if len(locked) >= lock.sample_size:
            break
    status = "complete" if len(locked) == lock.sample_size else "blocked"
    payload = {
        "status": status,
        "locked_instances": locked,
        "required": lock.sample_size,
        "gold_repetitions": lock.gold_repetitions,
        "instances": [
            {
                "instance_id": item.instance_id,
                "valid": item.valid,
                "exclusion_reason": item.exclusion_reason,
                "attempts": [attempt.__dict__ for attempt in item.attempts],
            }
            for item in results
        ],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return GoldPreflightResult(status, tuple(locked), tuple(results), str(output_path))


def _official_resolved(path: Path, instance_id: str) -> bool | None:
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    value = raw.get(instance_id) if isinstance(raw, dict) else None
    if isinstance(value, dict) and isinstance(value.get("resolved"), bool):
        return value["resolved"]
    if isinstance(raw, dict):
        resolved_ids = raw.get("resolved_ids")
        unresolved_ids = raw.get("unresolved_ids")
        if isinstance(resolved_ids, list) and instance_id in resolved_ids:
            return True
        if isinstance(unresolved_ids, list) and instance_id in unresolved_ids:
            return False
    return None


def _command_check(name: str, command: list[str], runner: CommandRunner) -> PreflightCheck:
    try:
        completed = runner(command, text=True, capture_output=True, timeout=30)
    except Exception as exc:
        return PreflightCheck(name, False, f"{type(exc).__name__}: {exc}")
    detail = (completed.stdout or completed.stderr).strip()[:1000]
    return PreflightCheck(name, completed.returncode == 0, detail)


def _network_check(name: str, url: str, *, attempts: int = 3) -> PreflightCheck:
    errors = []
    for attempt in range(1, attempts + 1):
        try:
            request = urllib.request.Request(
                url, headers={"User-Agent": "ArtCode-chTA/1"}
            )
            with urllib.request.urlopen(request, timeout=20) as response:
                return PreflightCheck(
                    name,
                    response.status < 400,
                    f"HTTP {response.status}; attempt={attempt}/{attempts}",
                )
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
            if attempt < attempts:
                time.sleep(1)
    curl = subprocess.run(
        [
            "curl",
            "--location",
            "--silent",
            "--show-error",
            "--output",
            "/dev/null",
            "--write-out",
            "%{http_code}",
            "--max-time",
            "30",
            url,
        ],
        text=True,
        capture_output=True,
    )
    if curl.returncode == 0 and curl.stdout.strip().isdigit():
        status = int(curl.stdout.strip())
        if status < 400:
            return PreflightCheck(name, True, f"HTTP {status}; transport=curl-fallback")
    errors.append(
        f"curl exit={curl.returncode}; status={curl.stdout.strip()}; {curl.stderr.strip()}"
    )
    return PreflightCheck(name, False, " | ".join(errors)[-2000:])


__all__ = [
    "EnvironmentPreflight",
    "GoldPreflightResult",
    "OfficialRunResult",
    "OfficialSWEbenchAdapter",
    "SWEbenchLock",
    "install_official_harness",
    "load_swebench_lock",
    "materialize_official_harness",
    "materialize_pinned_dataset",
    "run_environment_preflight",
    "run_gold_preflight",
]
