from __future__ import annotations

import asyncio
import shutil
import uuid
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from artcode.agent import DO_MODE, NORMAL_AGENT_MODE, PLAN_MODE
from artcode.agent.events import AgentEventType
from artcode.agent.request import AgentRunRequest
from artcode.bootstrap import AppOptions, Bootstrap
from artcode.permissions import PermissionMode, ShellPolicy
from artcode.persistence import SessionSelection

from .judge import JudgePort
from .metrics import build_attempt_metrics, trace_metric_values
from .models import (
    AttemptMetrics,
    AttemptResult,
    AttemptStatus,
    BenchmarkSpec,
    BenchmarkTask,
    JudgeResult,
    MetricValue,
)
from .redaction import Redactor
from .report import build_run_report, write_attempt, write_json, write_run_report
from .trace import RunTraceRecorder
from .verifiers import run_verifiers
from .workspace import (
    copy_fixture,
    diff_snapshots,
    snapshot_workspace,
    validate_fixture_tree,
)


@dataclass(frozen=True)
class AgentExecution:
    stop_reason: str | None
    final_response: str
    session_id: str | None
    current_request_preserved: bool | None


class AgentExecutor(Protocol):
    async def __call__(
        self,
        task: BenchmarkTask,
        *,
        workspace: Path,
        artcode_home: Path,
        config_path: Path,
        recorder: RunTraceRecorder,
    ) -> AgentExecution:
        ...


@dataclass(frozen=True)
class EvaluationRun:
    run_id: str
    output_dir: Path
    report_json: Path
    report_markdown: Path
    attempts: tuple[AttemptResult, ...]
    interrupted: bool

    @property
    def passed(self) -> bool:
        return bool(self.attempts) and all(
            attempt.status == AttemptStatus.PASSED for attempt in self.attempts
        )


class EvaluationRunner:
    def __init__(
        self,
        *,
        config_path: Path,
        output_root: Path,
        redactor: Redactor,
        judge: JudgePort | None = None,
        executor: AgentExecutor | None = None,
        repository: Path | None = None,
        model_info: dict[str, Any] | None = None,
    ) -> None:
        self.config_path = config_path.expanduser().resolve(strict=True)
        self.output_root = output_root.expanduser().resolve()
        self.redactor = redactor
        self.judge = judge
        self.executor = executor or execute_production_agent
        self.repository = repository
        self.model_info = dict(model_info or {"config": self.config_path.name})

    async def run(self, benchmark: BenchmarkSpec) -> EvaluationRun:
        run_id = uuid.uuid4().hex
        started = datetime.now(timezone.utc)
        run_dir = self._create_run_directory(benchmark, run_id, started)
        attempts: list[AttemptResult] = []
        interrupted = False
        try:
            for task in benchmark.tasks:
                for attempt_number in range(1, task.repetitions + 1):
                    attempts.append(
                        await self._run_attempt(
                            benchmark,
                            task,
                            attempt_number,
                            run_id=run_id,
                            run_dir=run_dir,
                        )
                    )
                    self._write_checkpoint(
                        benchmark,
                        attempts,
                        run_id=run_id,
                        run_dir=run_dir,
                        started=started,
                        interrupted=False,
                    )
        except (KeyboardInterrupt, asyncio.CancelledError):
            interrupted = True
            self._write_checkpoint(
                benchmark,
                attempts,
                run_id=run_id,
                run_dir=run_dir,
                started=started,
                interrupted=True,
            )
            if isinstance(asyncio.current_task(), asyncio.Task) and asyncio.current_task().cancelling():
                raise
        report_json, report_markdown = self._write_checkpoint(
            benchmark,
            attempts,
            run_id=run_id,
            run_dir=run_dir,
            started=started,
            interrupted=interrupted,
        )
        return EvaluationRun(
            run_id,
            run_dir,
            report_json,
            report_markdown,
            tuple(attempts),
            interrupted,
        )

    async def _run_attempt(
        self,
        benchmark: BenchmarkSpec,
        task: BenchmarkTask,
        attempt_number: int,
        *,
        run_id: str,
        run_dir: Path,
    ) -> AttemptResult:
        attempt_slug = str(attempt_number)
        workspace = run_dir / "workspaces" / task.id / attempt_slug
        artcode_home = run_dir / ".work" / task.id / attempt_slug / "home"
        trace_path = run_dir / "traces" / task.id / f"{attempt_slug}.jsonl"
        attempt_path = run_dir / "attempts" / task.id / f"{attempt_slug}.json"
        changes_path = run_dir / "workspaces" / task.id / f"{attempt_slug}-changes.json"
        recorder = RunTraceRecorder(
            trace_path,
            run_id=run_id,
            task_id=task.id,
            attempt=attempt_number,
            redactor=self.redactor,
        )
        recorder.start(
            {
                "benchmark_fingerprint": benchmark.fingerprint,
                "timeout_seconds": task.timeout_seconds,
                "max_iterations": task.max_iterations,
            }
        )
        status = AttemptStatus.SETUP_FAILED
        stop_reason: str | None = None
        final_response = ""
        error = ""
        session_id: str | None = None
        changes = ()
        verifications = ()
        judge_result = JudgeResult.disabled()
        setup_complete = False
        cancelled = False
        agent_task: asyncio.Task[AgentExecution] | None = None
        try:
            fixture = validate_fixture_tree(task.fixture, benchmark.source.parent)
            copy_fixture(fixture, workspace)
            artcode_home.mkdir(parents=True, exist_ok=False)
            before = snapshot_workspace(workspace, excluded_roots=(".artcode",))
            setup_complete = True
            agent_task = asyncio.create_task(
                self.executor(
                    task,
                    workspace=workspace,
                    artcode_home=artcode_home,
                    config_path=self.config_path,
                    recorder=recorder,
                )
            )
            done, _ = await asyncio.wait({agent_task}, timeout=task.timeout_seconds)
            if not done:
                agent_task.cancel()
                try:
                    await agent_task
                except asyncio.CancelledError:
                    pass
                status = AttemptStatus.TIMEOUT
                error = f"Agent 超过 {task.timeout_seconds:g} 秒"
                stop_reason = "timeout"
            else:
                execution = agent_task.result()
                stop_reason = execution.stop_reason
                final_response = execution.final_response
                session_id = execution.session_id
                recorder.append(
                    "evaluation_invariant",
                    {"current_request_preserved": execution.current_request_preserved},
                )
                status = (
                    AttemptStatus.PASSED
                    if stop_reason == "natural"
                    else AttemptStatus.CANCELLED
                    if stop_reason == "user_cancelled"
                    else AttemptStatus.AGENT_FAILED
                )
            after = snapshot_workspace(workspace, excluded_roots=(".artcode",))
            changes = diff_snapshots(before, after)
            write_json(changes_path, changes, redactor=self.redactor)
            preliminary = trace_metric_values(recorder.records)
            verifications = await run_verifiers(
                task.verifiers,
                workspace=workspace,
                trace=recorder.records,
                metrics=preliminary,
                redactor=self.redactor,
            )
            if self.judge is not None and task.judge is not None:
                judge_result = await self.judge.evaluate(
                    task,
                    final_response=final_response,
                    changes=changes,
                    verifications=verifications,
                )
            if status == AttemptStatus.PASSED and any(
                result.required and not result.passed for result in verifications
            ):
                status = AttemptStatus.VERIFICATION_FAILED
        except asyncio.CancelledError:
            if agent_task is not None and not agent_task.done():
                agent_task.cancel()
                try:
                    await agent_task
                except asyncio.CancelledError:
                    pass
            status = AttemptStatus.CANCELLED
            stop_reason = "user_cancelled"
            error = "评测被用户中断"
            cancelled = True
        except Exception as exc:
            error = self.redactor.preview(str(exc), limit=2000).text
            if status != AttemptStatus.TIMEOUT:
                status = (
                    AttemptStatus.AGENT_FAILED
                    if setup_complete
                    else AttemptStatus.SETUP_FAILED
                )
        finally:
            recorder.finish(
                {
                    "status": status.value,
                    "stop_reason": stop_reason,
                    "error": self.redactor.preview(error, limit=1000).text,
                }
            )

        metrics = build_attempt_metrics(
            recorder.records,
            verifications,
            passed=status == AttemptStatus.PASSED,
            judge=judge_result,
        )
        result = AttemptResult(
            run_id=run_id,
            task_id=task.id,
            attempt=attempt_number,
            status=status,
            stop_reason=stop_reason,
            final_response=self.redactor.preview(final_response, limit=4000).text,
            error=self.redactor.preview(error, limit=2000).text,
            workspace=str(workspace.relative_to(run_dir)),
            session_id=session_id,
            trace_path=str(trace_path.relative_to(run_dir)),
            attempt_path=str(attempt_path.relative_to(run_dir)),
            changes_path=str(changes_path.relative_to(run_dir)),
            verifications=verifications,
            metrics=metrics,
            judge=judge_result,
            changes=changes,
        )
        write_attempt(attempt_path, result, redactor=self.redactor)
        if cancelled:
            raise asyncio.CancelledError
        return result

    def _create_run_directory(
        self,
        benchmark: BenchmarkSpec,
        run_id: str,
        started: datetime,
    ) -> Path:
        self.output_root.mkdir(parents=True, exist_ok=True)
        fixture_roots = [task.fixture.resolve(strict=False) for task in benchmark.tasks]
        output = self.output_root.resolve()
        for fixture in fixture_roots:
            if output == fixture or fixture in output.parents:
                raise ValueError("输出目录不能位于 Benchmark Fixture 内")
        name = f"{started.strftime('%Y%m%dT%H%M%SZ')}-{benchmark.fingerprint[:8]}-{run_id[:8]}"
        run_dir = self.output_root / name
        run_dir.mkdir(parents=False, exist_ok=False)
        return run_dir

    def _write_checkpoint(
        self,
        benchmark: BenchmarkSpec,
        attempts: list[AttemptResult],
        *,
        run_id: str,
        run_dir: Path,
        started: datetime,
        interrupted: bool,
    ) -> tuple[Path, Path]:
        report = build_run_report(
            benchmark,
            attempts,
            run_id=run_id,
            model=self.model_info,
            started_at=started.isoformat(),
            interrupted=interrupted,
            repository=self.repository,
        )
        return write_run_report(run_dir, report, redactor=self.redactor)


async def execute_production_agent(
    task: BenchmarkTask,
    *,
    workspace: Path,
    artcode_home: Path,
    config_path: Path,
    recorder: RunTraceRecorder,
) -> AgentExecution:
    modes = {"normal": NORMAL_AGENT_MODE, "plan": PLAN_MODE, "do": DO_MODE}
    async with AsyncExitStack() as resources:
        application = await Bootstrap(
            AppOptions(
                config_path=config_path,
                workspace_path=workspace,
                artcode_home=artcode_home,
                session_selection=SessionSelection.new(),
            )
        ).build(resources)
        application.runtime.state.set_permission_mode(PermissionMode(task.permission_mode))
        application.runtime.state.set_shell_policy(ShellPolicy(task.shell_policy))
        final_response = ""
        stop_reason: str | None = None
        async for event in application.runtime.agent_loop.run(
            AgentRunRequest(
                user_content=task.prompt,
                mode=modes[task.mode],
                max_iterations=task.max_iterations,
            )
        ):
            recorder.record_agent_event(event)
            if event.type == AgentEventType.MODEL_TURN_COMPLETED:
                text = event.payload.get("text")
                if isinstance(text, str) and text:
                    final_response = text
            elif event.type == AgentEventType.STOPPED:
                value = event.payload.get("reason")
                stop_reason = str(value) if value is not None else None
        messages = application.runtime.conversation.export_messages()
        preserved = any(
            message.get("role") == "user" and message.get("content") == task.prompt
            for message in messages
        )
        return AgentExecution(
            stop_reason=stop_reason,
            final_response=final_response,
            session_id=application.runtime.session_service.status.session_id,
            current_request_preserved=preserved,
        )


__all__ = [
    "AgentExecution",
    "AgentExecutor",
    "EvaluationRun",
    "EvaluationRunner",
    "execute_production_agent",
]
