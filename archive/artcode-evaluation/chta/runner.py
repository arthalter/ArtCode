from __future__ import annotations

import asyncio
import json
import os
import platform
import subprocess
import sys
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from artcode.agent import (
    AgentLoop,
    AgentRunRequest,
    NORMAL_AGENT_MODE,
    RequestPreparer,
)
from artcode.config import ArtCodeConfig, load_config
from artcode.conversation import ConversationContext
from artcode.evaluation.manifest import load_chta_manifest
from artcode.evaluation.models import (
    ChTAExperiment,
    ChTAExperimentKind,
    ChTAManifest,
    to_jsonable,
)
from artcode.evaluation.redaction import Redactor
from artcode.evaluation.report import atomic_write_text
from artcode.evaluation.trace import RunTraceRecorder
from artcode.mcp import McpLoadingStrategy, McpManager, load_mcp_configuration
from artcode.permissions import ApprovalChoice, PermissionState
from artcode.permissions.service import PermissionService
from artcode.prompting.assembler import PromptRequestAssembler
from artcode.providers import DeepSeekChatProvider
from artcode.tools import ToolEnvironment, create_default_tool_registry
from artcode.tools.execution import ToolExecutionService

from .mcp_experiment import (
    McpAttemptObservation,
    McpExperimentRunner,
)
from .permission_experiment import (
    PermissionExperimentRunner,
    load_permission_operations,
)
from .compat_driver import ExternalCompatDriver
from .retention_probes import (
    build_retention_probes,
    load_driver_retention_results,
)
from .report import build_chta_report, write_chta_report_files
from .swebench_experiment import (
    SWEbenchAttempt,
    SWEbenchExperimentRunner,
)
from .swebench_live import (
    OfficialSWEbenchAdapter,
    install_official_harness,
    load_swebench_lock,
    materialize_official_harness,
    materialize_pinned_dataset,
    run_environment_preflight,
    run_gold_preflight,
)
from .workbook import write_chta_workbook
from .version_runner import VersionIsolationRunner, VersionWorkspace


EXPERIMENT_NAMES = frozenset({"mcp", "permission", "swebench", "all"})


@dataclass(frozen=True)
class McpTask:
    id: str
    query: str
    target_remote_name: str
    arguments: dict[str, Any]
    expected: str


@dataclass(frozen=True)
class ChTARunResult:
    run_id: str
    run_dir: Path
    status: str
    report_json: Path
    report_markdown: Path
    report_workbook: Path | None


class _AllowMcpApprover:
    async def request_mcp_approval(self, preview, plan_mode: bool) -> bool:
        return True

    async def request_approval(self, request) -> ApprovalChoice:
        return ApprovalChoice.DENY_ONCE


class ChTARunner:
    def __init__(
        self,
        manifest: ChTAManifest,
        *,
        output_root: Path,
        repository: Path,
        experiment: str,
        config_path: Path | None = None,
        node_binary: Path | None = None,
        node_modules: Path | None = None,
    ) -> None:
        if experiment not in EXPERIMENT_NAMES:
            raise ValueError(f"未知 chTA 实验：{experiment}")
        self.manifest = manifest
        self.output_root = output_root.expanduser().resolve()
        self.repository = repository.expanduser().resolve(strict=True)
        self.experiment = experiment
        self.config_path = config_path.expanduser().resolve() if config_path else None
        self.node_binary = node_binary
        self.node_modules = node_modules
        self.config = self._load_model_config_if_needed()
        self.redactor = Redactor([self.config.api_key] if self.config else [])

    async def run(self) -> ChTARunResult:
        run_id = self._new_run_id()
        run_dir = self.output_root / run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        self._write_run_lock(run_dir)
        results: dict[str, Any] = {}
        for name in self._selected_experiments():
            try:
                value = await self._run_one(name, run_dir)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                value = self._blocked(name, "runner", exc)
            results[name] = value
            self._write_experiment_result(run_dir, name, value)
        report = build_chta_report(
            self.manifest,
            run_id=run_id,
            experiments=results,
            evidence_root=run_dir,
        )
        report_json, report_markdown = write_chta_report_files(report, run_dir)
        workbook = self._write_workbook_or_evidence(report_json, run_dir)
        return ChTARunResult(
            run_id,
            run_dir,
            report["status"],
            report_json,
            report_markdown,
            workbook,
        )

    def _load_model_config_if_needed(self) -> ArtCodeConfig | None:
        if self.experiment not in {"mcp", "swebench", "all"}:
            return None
        path = self.config_path or Path.home() / ".artcode" / "config.yml"
        config = load_config(path)
        return replace(config, model=self.manifest.model.name)

    def _selected_experiments(self) -> tuple[str, ...]:
        if self.experiment == "all":
            return ("mcp", "permission", "swebench")
        return (self.experiment,)

    async def _run_one(self, name: str, run_dir: Path) -> dict[str, Any]:
        if name == "mcp":
            return await self._run_mcp(run_dir / "mcp")
        if name == "permission":
            return await self._run_permission(run_dir / "permission")
        return await asyncio.to_thread(self._run_swebench, run_dir / "swebench")

    async def _run_mcp(self, output_dir: Path) -> dict[str, Any]:
        if self.config is None:
            raise RuntimeError("MCP 真实 A/B 缺少模型配置")
        experiment = self._manifest_experiment(ChTAExperimentKind.MCP)
        task_path = self.repository / "benchmarks" / "chTA" / "mcp" / "tasks.yml"
        tasks = {item.id: item for item in load_mcp_tasks(task_path)}
        fixture = (
            self.repository
            / "benchmarks"
            / "chTA"
            / "mcp"
            / "hundred_tools_server.py"
        )
        if not fixture.is_file():
            raise FileNotFoundError(f"MCP 百级 Fixture 缺失：{fixture}")

        async def execute(profile: str, task_id: str, repetition: int):
            return await self._execute_mcp_attempt(
                experiment,
                tasks[task_id],
                profile,
                repetition,
                fixture,
                output_dir,
            )

        result = await McpExperimentRunner(experiment, execute).run()
        payload = to_jsonable(result)
        evidence_complete = all(
            item.get("evidence_path") and Path(item["evidence_path"]).is_file()
            for item in payload["attempts"]
        )
        payload["evidence_complete"] = evidence_complete
        if not evidence_complete:
            payload["status"] = "partial"
        return payload

    async def _execute_mcp_attempt(
        self,
        experiment: ChTAExperiment,
        task: McpTask,
        profile: str,
        repetition: int,
        fixture: Path,
        output_dir: Path,
    ) -> McpAttemptObservation:
        strategy = McpLoadingStrategy(profile)
        root = output_dir / profile / task.id / f"attempt-{repetition}"
        workspace = root / "workspace"
        workspace.mkdir(parents=True, exist_ok=False)
        trace_path = root / "trace.jsonl"
        recorder = RunTraceRecorder(
            trace_path,
            run_id=f"chta-mcp-{profile}",
            task_id=task.id,
            attempt=repetition,
            redactor=self.redactor,
        )
        recorder.start(
            {
                "profile": profile,
                "strategy": strategy.value,
                "task": task.id,
                "repetition": repetition,
            }
        )
        raw = {
            "mcp_servers": {
                "chta_fixture": {
                    "transport": "stdio",
                    "command": sys.executable,
                    "args": [str(fixture)],
                }
            }
        }
        configs, issues = load_mcp_configuration(raw, workspace)
        manager = McpManager(configs, workspace, issues, loading=strategy)
        provider = DeepSeekChatProvider(self.config)
        error = ""
        success = False
        try:
            startup = await manager.start()
            if startup.discovered_tool_count != 120:
                raise RuntimeError(
                    f"MCP Fixture 应发现 120 个工具，实际 {startup.discovered_tool_count}"
                )
            registry = create_default_tool_registry()
            conflicts = manager.register_into(registry)
            if conflicts:
                raise RuntimeError("MCP 注册冲突：" + "；".join(conflicts))
            target = next(
                (
                    adapter
                    for adapter in manager.adapters
                    if adapter.remote_name == task.target_remote_name
                ),
                None,
            )
            if target is None:
                raise RuntimeError(f"MCP 目标工具不存在：{task.target_remote_name}")
            conversation = ConversationContext()
            state = PermissionState()
            environment = ToolEnvironment.from_workspace(workspace)
            permissions = PermissionService(state, approver=_AllowMcpApprover())
            executor = ToolExecutionService(registry, environment, permissions)
            preparer = RequestPreparer(
                conversation,
                PromptRequestAssembler(),
                registry,
                environment,
                state,
            )
            loop = AgentLoop(
                provider,
                conversation,
                registry,
                environment,
                tool_executor=executor,
                request_preparer=preparer,
            )
            prompt = _mcp_prompt(task)
            async for event in loop.run(
                AgentRunRequest(
                    prompt,
                    NORMAL_AGENT_MODE,
                    max_iterations=min(experiment.parameters.get("max_iterations", 8), 8),
                    final_summary_on_abnormal_stop=False,
                )
            ):
                recorder.record_agent_event(event)
            success = any(
                record.kind == "tool_result"
                and record.payload.get("tool_name") == target.name
                and record.payload.get("ok") is True
                and task.expected in str(record.payload.get("output_preview", ""))
                for record in recorder.records
            )
            if not success:
                error = _last_stop_error(recorder.records) or "目标 MCP 工具未成功返回预期值"
        except asyncio.CancelledError:
            recorder.close_partial()
            raise
        except Exception as exc:
            error = self.redactor.redact(f"{type(exc).__name__}: {exc}")
        finally:
            await provider.close()
            await manager.close()
            recorder.finish({"success": success, "error": error})
        return McpAttemptObservation(
            profile,
            task.id,
            repetition,
            success,
            tuple(recorder.records),
            str(trace_path),
            error,
        )

    async def _run_permission(self, output_dir: Path) -> dict[str, Any]:
        operations = load_permission_operations(
            self.repository
            / "benchmarks"
            / "chTA"
            / "permission"
            / "operations.yml"
        )
        result = await PermissionExperimentRunner(
            operations,
            output_dir=output_dir,
            redactor=self.redactor,
        ).run()
        payload = to_jsonable(result)
        evidence_paths = (
            Path(payload["baseline"]["evidence_path"]),
            Path(payload["candidate"]["evidence_path"]),
        )
        payload["evidence_complete"] = all(path.is_file() for path in evidence_paths)
        return payload

    def _run_swebench(self, output_dir: Path) -> dict[str, Any]:
        output_dir.mkdir(parents=True, exist_ok=False)
        environment = run_environment_preflight(output_dir / "gold-preflight")
        payload: dict[str, Any] = {
            "status": "blocked",
            "evidence_complete": False,
            "phase": "environment_preflight",
            "environment": to_jsonable(environment),
        }
        if environment.status != "ready":
            return payload
        lock = load_swebench_lock(
            self.repository / "benchmarks" / "chTA" / "swebench" / "lock.yml"
        )
        harness = materialize_official_harness(
            self.manifest.revisions.swebench_repository,
            self.manifest.revisions.swebench_revision,
            output_dir / "official-harness",
        )
        python = install_official_harness(harness, output_dir / "official-venv")
        dataset = materialize_pinned_dataset(
            python,
            self.manifest.revisions,
            output_dir / "dataset" / "verified.json",
        )
        adapter = OfficialSWEbenchAdapter(
            python=python,
            repository=harness,
            dataset_json=dataset,
            namespace=lock.namespace,
            output_dir=output_dir / "gold-runs",
            timeout_seconds=int(self.manifest.budget.timeout_seconds),
        )
        gold = run_gold_preflight(
            adapter,
            lock,
            output_dir / "gold-preflight" / "gold-lock.json",
        )
        payload.update(
            {
                "phase": "gold_preflight" if gold.status != "complete" else "agent_runs",
                "gold_preflight": to_jsonable(gold),
                "gold_valid_instances": list(gold.locked_instances),
            }
        )
        if gold.status != "complete":
            return payload
        if self.config is None:
            raise RuntimeError("SWE-bench 历史 Agent A/B 缺少模型配置")
        rows = json.loads(dataset.read_text(encoding="utf-8"))
        if not isinstance(rows, list):
            raise ValueError("锁定 SWE-bench 数据集不是实例列表")
        instances = {
            item.get("instance_id"): item
            for item in rows
            if isinstance(item, dict) and isinstance(item.get("instance_id"), str)
        }
        missing = [item for item in gold.locked_instances if item not in instances]
        if missing:
            raise ValueError("gold-valid 实例未出现在锁定数据集：" + "、".join(missing))
        profile_experiment = self._manifest_experiment(ChTAExperimentKind.SWEBENCH)
        isolation = VersionIsolationRunner(self.repository, output_dir / "versions")
        version_workspaces = {
            profile_experiment.baseline.id: isolation.materialize(
                profile_experiment.baseline.id,
                self.manifest.revisions.baseline_commit,
            ),
            profile_experiment.candidate.id: isolation.materialize(
                profile_experiment.candidate.id,
                self.manifest.revisions.candidate_commit,
            ),
        }
        for profile, version in version_workspaces.items():
            for instance_id in gold.locked_instances:
                _materialize_instance_repository(
                    instances[instance_id],
                    version.workspace / _safe_instance_directory(instance_id),
                )
            isolation.assert_context_unchanged(version)
        driver = ExternalCompatDriver()
        agent_driver = (
            self.repository
            / "benchmarks"
            / "chTA"
            / "swebench"
            / "agent_driver.py"
        )
        retention_driver = (
            self.repository
            / "benchmarks"
            / "chTA"
            / "swebench"
            / "retention_driver.py"
        )
        official_agent = OfficialSWEbenchAdapter(
            python=python,
            repository=harness,
            dataset_json=dataset,
            namespace=lock.namespace,
            output_dir=output_dir / "agent-official-runs",
            timeout_seconds=int(self.manifest.budget.timeout_seconds),
        )

        async def attempt_executor(profile: str, instance_id: str) -> SWEbenchAttempt:
            version = version_workspaces[profile]
            instance = instances[instance_id]
            label = f"agent-{_safe_instance_directory(instance_id)}"
            result = await asyncio.to_thread(
                driver.run,
                version,
                agent_driver,
                {
                    "repository_dir": _safe_instance_directory(instance_id),
                    "prompt": _swebench_agent_prompt(instance),
                    "max_iterations": self.manifest.budget.max_iterations,
                    "command_timeout_seconds": min(
                        self.manifest.budget.timeout_seconds, 300
                    ),
                    "context_window_tokens": 1_000_000,
                },
                label=label,
                environment={
                    "ARTCODE_EVAL_API_KEY": self.config.api_key,
                    "ARTCODE_EVAL_BASE_URL": self.config.base_url,
                    "ARTCODE_EVAL_MODEL": self.config.model,
                },
                timeout_seconds=int(self.manifest.budget.timeout_seconds),
            )
            isolation.assert_context_unchanged(version)
            if result.status != "complete":
                return SWEbenchAttempt(
                    profile,
                    instance_id,
                    False,
                    "",
                    result.output_path,
                    result.log_path,
                    result.error,
                )
            driver_output = json.loads(
                Path(result.output_path).read_text(encoding="utf-8")
            )
            patch_path = Path(driver_output["patch_path"])
            patch = patch_path.read_text(encoding="utf-8")
            official = await asyncio.to_thread(
                official_agent.run_patch,
                instance_id,
                profile,
                patch,
            )
            return SWEbenchAttempt(
                profile,
                instance_id,
                official.resolved is True,
                str(patch_path),
                result.output_path,
                official.stdout_path,
                official.error,
            )

        async def retention_executor(profile: str, instance_id: str):
            version = version_workspaces[profile]
            prompt, probes = build_retention_probes(instances[instance_id])
            result = await asyncio.to_thread(
                driver.run,
                version,
                retention_driver,
                {
                    "prompt": prompt,
                    "probes": [
                        {
                            "id": item.id,
                            "category": item.category,
                            "expected": item.expected,
                            "expected_sha256": item.expected_sha256,
                            "required_role": item.required_role,
                        }
                        for item in probes
                    ],
                },
                label=f"retention-{_safe_instance_directory(instance_id)}",
                timeout_seconds=300,
            )
            isolation.assert_context_unchanged(version)
            if result.status != "complete":
                return ()
            return load_driver_retention_results(
                Path(result.output_path),
                instance_id=instance_id,
                profile=profile,
                probes=probes,
            )

        result = asyncio.run(
            SWEbenchExperimentRunner(
                gold.locked_instances,
                baseline=profile_experiment.baseline.id,
                candidate=profile_experiment.candidate.id,
                attempt_executor=attempt_executor,
                retention_executor=retention_executor,
            ).run()
        )
        payload.update(to_jsonable(result))
        evidence_paths = [
            path
            for item in payload.get("attempts", [])
            for path in (
                item.get("patch_path"),
                item.get("trace_path"),
                item.get("official_log_path"),
            )
        ]
        payload["evidence_complete"] = bool(evidence_paths) and all(
            path and Path(path).is_file() for path in evidence_paths
        )
        if not payload["evidence_complete"]:
            payload["status"] = "partial"
        return payload

    def _manifest_experiment(self, kind: ChTAExperimentKind) -> ChTAExperiment:
        return next(item for item in self.manifest.experiments if item.kind is kind)

    def _new_run_id(self) -> str:
        stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
        base = f"{stamp}-{self.manifest.fingerprint[:8]}"
        candidate = base
        counter = 1
        while (self.output_root / candidate).exists():
            counter += 1
            candidate = f"{base}-{counter}"
        return candidate

    def _write_run_lock(self, run_dir: Path) -> None:
        lock = {
            "schema_version": 1,
            "manifest": to_jsonable(self.manifest),
            "selected_experiment": self.experiment,
            "environment": {
                "python": platform.python_version(),
                "platform": platform.platform(),
                "machine": platform.machine(),
                "repository_head": _git_value(self.repository, "HEAD"),
                "repository_dirty": bool(_git_status(self.repository)),
                "model": self.config.model if self.config else self.manifest.model.name,
                "base_url": self.redactor.redact(self.config.base_url) if self.config else None,
            },
        }
        atomic_write_text(
            run_dir / "manifest.lock.json",
            json.dumps(lock, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )

    def _write_experiment_result(
        self, run_dir: Path, name: str, value: dict[str, Any]
    ) -> None:
        target = run_dir / name / "result.json"
        atomic_write_text(
            target,
            json.dumps(self.redactor.redact_value(value), ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
        )

    def _write_workbook_or_evidence(
        self, report_json: Path, run_dir: Path
    ) -> Path | None:
        try:
            return write_chta_workbook(
                report_json,
                run_dir / "report.xlsx",
                node_binary=self.node_binary,
                node_modules=self.node_modules,
            )
        except Exception as exc:
            atomic_write_text(
                run_dir / "report-workbook.error.txt",
                self.redactor.redact(f"{type(exc).__name__}: {exc}") + "\n",
            )
            return None

    def _blocked(self, name: str, phase: str, exc: Exception) -> dict[str, Any]:
        return {
            "status": "blocked",
            "evidence_complete": False,
            "phase": phase,
            "experiment": name,
            "error": self.redactor.redact(f"{type(exc).__name__}: {exc}"),
        }


def regenerate_chta_report(
    run_dir: Path,
    *,
    node_binary: Path | None = None,
    node_modules: Path | None = None,
) -> tuple[Path, Path, Path]:
    run_dir = run_dir.expanduser().resolve(strict=True)
    report_json = run_dir / "report.json"
    try:
        report = json.loads(report_json.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取 chTA report.json：{exc}") from exc
    if not isinstance(report, dict) or report.get("schema_version") != 1:
        raise ValueError("chTA report.json schema 无效")
    _, markdown = write_chta_report_files(report, run_dir)
    workbook = write_chta_workbook(
        report_json,
        run_dir / "report.xlsx",
        node_binary=node_binary,
        node_modules=node_modules,
    )
    return report_json, markdown, workbook


def load_mcp_tasks(path: Path) -> tuple[McpTask, ...]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ValueError(f"无法读取 MCP 任务清单：{exc}") from exc
    if not isinstance(raw, dict) or set(raw) != {"version", "tasks"}:
        raise ValueError("MCP 任务清单字段不完整或包含未知字段")
    if raw["version"] != 1 or not isinstance(raw["tasks"], list):
        raise ValueError("MCP 任务清单 version/tasks 无效")
    tasks = []
    fields = {"id", "query", "target_remote_name", "arguments", "expected"}
    for index, item in enumerate(raw["tasks"]):
        if not isinstance(item, dict) or set(item) != fields:
            raise ValueError(f"MCP tasks[{index}] 字段无效")
        if any(
            not isinstance(item[field], str) or not item[field]
            for field in ("id", "query", "target_remote_name", "expected")
        ) or not isinstance(item["arguments"], dict):
            raise ValueError(f"MCP tasks[{index}] 值无效")
        tasks.append(
            McpTask(
                item["id"],
                item["query"],
                item["target_remote_name"],
                dict(item["arguments"]),
                item["expected"],
            )
        )
    if len(tasks) != 5 or len({item.id for item in tasks}) != len(tasks):
        raise ValueError("MCP 任务清单必须包含 5 个唯一任务")
    return tuple(tasks)


def _mcp_prompt(task: McpTask) -> str:
    arguments = json.dumps(task.arguments, ensure_ascii=False, sort_keys=True)
    return (
        "你正在执行确定性 MCP 评测。必须调用工具完成任务，不得猜测结果。"
        f"目标能力：{task.query}；目标远程工具名：{task.target_remote_name}；"
        f"参数必须严格为 {arguments}。如果目标工具当前不可见，先调用 "
        f"mcp_search_tools 检索 {task.query!r}，下一轮再调用新激活的目标工具。"
        "得到工具返回后，用一句话复述结果。"
    )


def _safe_instance_directory(instance_id: str) -> str:
    if not instance_id or any(
        character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-"
        for character in instance_id
    ):
        raise ValueError(f"SWE-bench instance_id 不能安全映射目录：{instance_id!r}")
    return instance_id


def _materialize_instance_repository(instance: dict[str, Any], target: Path) -> None:
    repo = instance.get("repo")
    base_commit = instance.get("base_commit")
    if (
        not isinstance(repo, str)
        or repo.count("/") != 1
        or any(part in {"", ".", ".."} for part in repo.split("/"))
        or not isinstance(base_commit, str)
        or len(base_commit) != 40
        or any(character not in "0123456789abcdef" for character in base_commit.lower())
    ):
        raise ValueError("SWE-bench 实例 repo/base_commit 无效")
    if target.exists():
        raise FileExistsError(f"SWE-bench 隔离仓库已存在：{target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    commands = (
        [
            "git",
            "clone",
            "--filter=blob:none",
            "--no-checkout",
            f"https://github.com/{repo}.git",
            str(target),
        ],
        ["git", "-C", str(target), "fetch", "--depth", "1", "origin", base_commit],
        ["git", "-C", str(target), "checkout", "--detach", "FETCH_HEAD"],
    )
    for command in commands:
        completed = subprocess.run(
            command,
            text=True,
            capture_output=True,
            timeout=300,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"SWE-bench 仓库 materialize 失败：{' '.join(command[:4])}："
                f"{completed.stderr[-2000:]}"
            )
    resolved = _git_value(target, "HEAD")
    if resolved.lower() != base_commit.lower():
        raise RuntimeError(
            f"SWE-bench 仓库提交不匹配：expected={base_commit}; actual={resolved}"
        )


def _swebench_agent_prompt(instance: dict[str, Any]) -> str:
    problem = instance.get("problem_statement")
    if not isinstance(problem, str) or not problem.strip():
        raise ValueError("SWE-bench 实例缺少 problem_statement")
    hints = instance.get("hints_text")
    hint_section = f"\n\n补充提示：\n{hints}" if isinstance(hints, str) and hints else ""
    return (
        "你正在固定提交的真实代码仓库中解决一个 SWE-bench-Live 问题。"
        "请先检查相关文件和测试，再实施最小但完整的修复；可以运行测试。"
        "只修改当前仓库，禁止提交 commit，完成后简洁说明修改与验证。\n\n"
        f"问题原文：\n{problem.strip()}{hint_section}"
    )


def _last_stop_error(records) -> str:
    for record in reversed(records):
        if record.kind == "stopped":
            reason = record.payload.get("reason", "")
            message = record.payload.get("message", "")
            return f"stop={reason}; {message}".strip()
    return ""


def _git_value(repository: Path, revision: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", revision],
        text=True,
        capture_output=True,
    )
    return completed.stdout.strip() if completed.returncode == 0 else ""


def _git_status(repository: Path) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repository), "status", "--porcelain"],
        text=True,
        capture_output=True,
    )
    return completed.stdout if completed.returncode == 0 else "unknown"


__all__ = [
    "ChTARunResult",
    "ChTARunner",
    "McpTask",
    "load_mcp_tasks",
    "regenerate_chta_report",
]
