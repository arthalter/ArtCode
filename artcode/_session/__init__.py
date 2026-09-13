"""Local append-only implementation of the public Session Interface."""

from __future__ import annotations

from pathlib import Path
from dataclasses import replace
import asyncio
import time
from typing import Callable
import uuid

from artcode.core.model import Model, ModelMessage, ModelRequest, ProtocolMetadata, ToolRequest, Usage
from artcode.core.session import (
    AssistantCompletion,
    AssistantFact,
    CompactionReport,
    CompactionTrigger,
    DispatchedRun,
    PromptBudget,
    PreparedRequest,
    RunCompletion,
    RunContribution,
    RunLease,
    SelectionKind,
    SessionBusy,
    SessionCorrupt,
    SessionSelection,
    SessionSnapshot,
    TranscriptFact,
    ToolExchangeFact,
    UserFact,
)
from artcode.core.tool import RunMode, ToolResult, ToolRun

from .instructions import load_instructions
from .locking import SessionLock
from .memory import MemoryManager
from .notices import DerivedStateStore, add_notice
from .paths import (
    new_session_id,
    read_metadata,
    sessions_root,
    validate_session_id,
    write_metadata,
)
from .recovery import recover_transcript
from .prompt import (
    contribution_messages,
    instruction_messages,
    project_facts,
    read_memory,
    summary_message,
    with_notices,
)
from .continuation import FrozenProjection, RunProjection
from .results import estimate_request
from .storage import append_record, encode_record
from .summaries import generate_summary
from .transcript import complete_exchange, fact_payload


class LocalSession:
    def __init__(
        self,
        workspace: Path,
        selection: SessionSelection,
        *,
        clock: Callable[[], float] = time.time,
        user_home: Path | None = None,
        context_window_tokens: int = 1_000_000,
        recent_fact_count: int = 8,
        resume_notice_after_seconds: float = 24 * 60 * 60,
        storage_root: Path | None = None,
    ) -> None:
        candidate = workspace.expanduser()
        if not candidate.exists() or not candidate.is_dir():
            raise ValueError("Session Workspace 必须是已有目录。")
        self.workspace = candidate.resolve(strict=True)
        storage_candidate = (storage_root or self.workspace).expanduser()
        if not storage_candidate.exists() or not storage_candidate.is_dir():
            raise ValueError("Session storage_root 必须是已有目录。")
        self._storage_root = storage_candidate.resolve(strict=True)
        self._root = sessions_root(self._storage_root)
        self._clock = clock
        if context_window_tokens < 1 or recent_fact_count < 0 or resume_notice_after_seconds <= 0:
            raise ValueError("Session 上下文、近期历史和恢复提醒限制必须有效。")
        self._context_window_tokens = context_window_tokens
        self._recent_fact_count = recent_fact_count
        self._resume_notice_after_seconds = resume_notice_after_seconds
        self._user_home = (user_home or (Path.home() / ".artcode")).expanduser().resolve(strict=False)
        self._closed = False
        self._write_failed = False
        self._lock: SessionLock | None = None
        self._facts: tuple[TranscriptFact, ...] = ()
        self._issues: tuple[str, ...] = ()
        if selection.kind is SelectionKind.EXACT:
            assert selection.session_id is not None
            validate_session_id(selection.session_id)
        self._root.mkdir(parents=True, exist_ok=True, mode=0o700)

        if selection.kind is SelectionKind.NEW:
            self._create()
        elif selection.kind is SelectionKind.EXACT:
            assert selection.session_id is not None
            self._restore_exact(selection.session_id)
        else:
            if not self._restore_latest():
                self._create()
        self._initialize_derived()

    @property
    def archive_path(self) -> Path:
        return self._directory / "transcript.jsonl"

    @property
    def instruction_issues(self) -> tuple[str, ...]:
        return self._instruction_issues

    @property
    def instruction_text(self) -> str:
        return "\n".join(item.text for item in self._instructions)

    def snapshot(self) -> SessionSnapshot:
        self._ensure_open()
        return SessionSnapshot(
            self._session_id,
            self._created_at,
            self._restored,
            self._facts,
            self._issues,
            self._state.latest_plan,
            tuple(text for _, text in self._state.notices),
            self._state.summary is not None,
            self._state.last_usage,
            self._memory.pending,
            self._memory.last_report,
        )

    def commit_user(self, text: str) -> SessionSnapshot:
        if not isinstance(text, str):
            raise TypeError("User fact 必须是字符串。")
        return self._append(UserFact(text))

    def commit_assistant(
        self, text: str, completion: AssistantCompletion
    ) -> SessionSnapshot:
        if not isinstance(text, str) or not isinstance(completion, AssistantCompletion):
            raise ValueError("只允许提交自然完成或长度结束的 Assistant 文本。")
        return self._append(AssistantFact(text, completion))

    def commit_tool_exchange(
        self,
        requests: tuple[ToolRequest, ...],
        results: tuple[ToolResult, ...],
        *,
        metadata: ProtocolMetadata | None = None,
        cancelled: bool = False,
        assistant_text: str = "",
    ) -> SessionSnapshot:
        fact = complete_exchange(
            requests,
            results,
            metadata=metadata,
            cancelled=cancelled,
            assistant_text=assistant_text,
        )
        return self._append(fact)

    def add_notice(self, text: str) -> SessionSnapshot:
        self._ensure_open()
        identifier = add_notice(self._state, text)
        try:
            self._state_store.save(self._state)
        except BaseException:
            self._state.notices = [item for item in self._state.notices if item[0] != identifier]
            raise
        return self.snapshot()

    async def prepare_run(
        self,
        goal: str,
        tools: ToolRun,
        *,
        contributions: tuple[RunContribution, ...] = (),
        model_for_compaction: Model | None = None,
        frozen_prompt: ModelRequest | None = None,
    ) -> RunLease:
        self._ensure_open()
        if not isinstance(goal, str) or not goal.strip():
            raise ValueError("Run goal 必须是非空字符串。")
        if not isinstance(tools, ToolRun):
            raise TypeError("tools 必须是 ToolRun 快照。")
        if not all(isinstance(item, RunContribution) for item in contributions):
            raise TypeError("contributions 必须是 RunContribution tuple。")
        if frozen_prompt is not None and not isinstance(frozen_prompt, ModelRequest):
            raise TypeError("frozen_prompt 必须是 ModelRequest。")
        self.commit_user(goal)
        selected_model = next((item.model for item in reversed(contributions) if item.model is not None), None)
        if frozen_prompt is None:
            prefix = instruction_messages(
                self._instructions, contributions,
                read_memory(self._memory.user_index), read_memory(self._memory.project_index),
            )
            template = ModelRequest(prefix, model=selected_model)
            facts = self._facts
            offset = 0
            summary, through = self._state.summary, self._state.summary_through
        else:
            prefix = (*frozen_prompt.prompt, *contribution_messages(contributions))
            template = replace(frozen_prompt, model=selected_model or frozen_prompt.model)
            facts = (self._facts[-1],)
            offset = len(self._facts) - 1
            summary, through = None, 0
        frozen = FrozenProjection(tuple(prefix), template, len(frozen_prompt.prompt) if frozen_prompt else 0)
        request = frozen.render(facts, tools, summary, through)
        projection = RunProjection(frozen, facts, len(self._facts), offset, summary, through, request)
        estimate = estimate_request(request)
        if model_for_compaction is not None and estimate.tokens >= self._threshold:
            candidate, report = await self._compact_projection(
                projection, tools, model_for_compaction, CompactionTrigger.AUTOMATIC,
            )
            if report.status == "success":
                request = candidate
                estimate = estimate_request(request)
        budget = (
            PromptBudget(self._state.last_usage.input_tokens, "provider_usage")
            if self._state.last_usage is not None
            and self._state.last_usage.input_tokens is not None
            else estimate
        )
        lease = RunLease(
            uuid.uuid4().hex,
            goal,
            tools.mode,
            tools,
            request,
            tuple(self._state.notices),
            len(self._facts),
            budget,
        )
        self._leases[lease.id] = lease
        self._projections[lease.id] = projection
        return lease

    def dispatch_run(self, lease: RunLease) -> DispatchedRun:
        self._ensure_open()
        if self._leases.get(lease.id) != lease:
            raise ValueError("Run lease 不属于当前 Session 或已变化。")
        existing = self._dispatched.get(lease.id)
        if existing is not None:
            return existing
        pending_ids = {identifier for identifier, _ in self._state.notices}
        selected = tuple(item for item in lease.pending_notices if item[0] in pending_ids)
        projection = self._projections[lease.id]
        insertion = projection.frozen.parent_prefix_size or 1
        request = with_notices(lease.prompt_preview, selected, insertion=insertion)
        if selected:
            selected_ids = {identifier for identifier, _ in selected}
            original = list(self._state.notices)
            self._state.notices = [item for item in self._state.notices if item[0] not in selected_ids]
            try:
                self._state_store.save(self._state)
            except BaseException:
                self._state.notices = original
                raise
        if selected:
            static = replace(projection.frozen.template, prompt=projection.frozen.prefix)
            prefix = with_notices(static, selected, insertion=insertion).prompt
            projection.frozen = replace(projection.frozen, prefix=prefix)
        projection.request = request
        dispatched = DispatchedRun(lease, request)
        self._dispatched[lease.id] = dispatched
        return dispatched

    @property
    def _threshold(self) -> int:
        return self._context_window_tokens * 167 // 200

    async def prepare_next_request(
        self,
        lease: RunLease,
        request: ModelRequest,
        tools: ToolRun,
        *,
        model: Model,
        usage: Usage | None = None,
        trigger: CompactionTrigger = CompactionTrigger.AUTOMATIC,
    ) -> PreparedRequest:
        self._ensure_open()
        if self._leases.get(lease.id) != lease or lease.id not in self._dispatched:
            raise ValueError("只能准备已经 dispatch 的当前 Run lease。")
        if not isinstance(trigger, CompactionTrigger):
            raise TypeError("trigger 必须是 CompactionTrigger。")
        if not isinstance(tools, ToolRun):
            raise TypeError("tools 必须是 ToolRun 快照。")
        original_tools = lease.tools
        if any(getattr(tools, field) != getattr(original_tools, field) for field in (
            "mode", "source", "permission", "workspace", "catalog_id", "allowed_tools"
        )):
            raise ValueError("后续工具快照不能更改当前 Run 的权限和作用域。")
        projection = self._projections[lease.id]
        previous_estimate = estimate_request(projection.request)
        projection.accept(request, self._facts)
        if usage is not None and usage is not projection.last_usage:
            if not isinstance(usage, Usage):
                raise TypeError("usage 必须是最近一次请求的 Provider Usage。")
            projection.last_usage = usage
            if usage.input_tokens is not None:
                projection.usage_adjustment = usage.input_tokens - previous_estimate.tokens
        # Rebuild from explicit, frozen sources; never refresh instructions or memory.
        current = projection.frozen.render(projection.facts, tools, projection.summary, projection.summary_through)
        projection.request = current
        budget = self._request_budget(projection, current)
        report = None
        if budget.tokens >= self._threshold or trigger is CompactionTrigger.EMERGENCY:
            current, report = await self._compact_projection(projection, tools, model, trigger)
            budget = self._request_budget(projection, current)
        can_continue = budget.tokens < self._context_window_tokens
        detail = "" if can_continue else "当前请求超过上下文预算，且没有可安全缩短的历史。"
        return PreparedRequest(current, budget, report, can_continue, detail)

    def _request_budget(
        self, projection: RunProjection, request: ModelRequest
    ) -> PromptBudget:
        estimate = estimate_request(request)
        if projection.usage_adjustment is None:
            return estimate
        return PromptBudget(max(1, estimate.tokens + projection.usage_adjustment), "provider_usage_delta")

    async def _compact_projection(
        self,
        projection: RunProjection,
        tools: ToolRun,
        model: Model,
        trigger: CompactionTrigger,
    ) -> tuple[ModelRequest, CompactionReport]:
        # Keep the latest complete fact even when recent_fact_count is configured as zero.
        end = max(projection.summary_through, len(projection.facts) - max(1, self._recent_fact_count))
        latest_exchange = next((
            index for index in range(len(projection.facts) - 1, projection.summary_through - 1, -1)
            if isinstance(projection.facts[index], ToolExchangeFact)
        ), None)
        if latest_exchange is not None and not any(
            isinstance(fact, AssistantFact)
            for fact in projection.facts[latest_exchange + 1:]
        ):
            end = min(end, latest_exchange)
        start = projection.summary_through
        compactable = sum(not isinstance(fact, UserFact) for fact in projection.facts[start:end])
        if not compactable:
            return projection.request, CompactionReport(trigger, "noop")
        key = projection.fact_offset + end
        if projection.unsuccessful_attempts >= 3:
            return projection.request, CompactionReport(trigger, "noop", detail="本 Run 连续三次压缩未成功，已停止自动重试。")
        if key in projection.attempted:
            return projection.request, CompactionReport(trigger, "noop", detail="同一历史前缀已尝试压缩。")
        projection.attempted.add(key)
        projection.unsuccessful_attempts += 1
        try:
            summary = await generate_summary(model, projection.facts, start=start, end=end, previous_summary=projection.summary)
            candidate = projection.frozen.render(projection.facts, tools, summary, end)
            if estimate_request(candidate).tokens >= estimate_request(projection.request).tokens:
                return projection.request, CompactionReport(trigger, "noop", detail="候选摘要没有缩短完整请求。")
            previous = self._state.summary, self._state.summary_through
            self._state.summary, self._state.summary_through = summary, projection.fact_offset + end
            try:
                self._state_store.save(self._state)
            except BaseException:
                self._state.summary, self._state.summary_through = previous
                raise
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return projection.request, CompactionReport(trigger, "failed", detail=str(exc))
        projection.summary, projection.summary_through, projection.request = summary, end, candidate
        projection.unsuccessful_attempts = 0
        # The old Provider measurement describes the uncompressed request only.
        projection.usage_adjustment = None
        return candidate, CompactionReport(trigger, "success", compactable)

    def finish_run(
        self,
        lease: RunLease,
        completion: RunCompletion,
        *,
        assistant_text: str = "",
        usage: Usage | None = None,
    ) -> SessionSnapshot:
        self._ensure_open()
        if self._leases.get(lease.id) != lease or lease.id not in self._dispatched:
            raise ValueError("只能完成已经 dispatch 的 Run lease。")
        if not isinstance(completion, RunCompletion):
            raise TypeError("completion 必须是 RunCompletion。")
        if completion in {RunCompletion.NATURAL, RunCompletion.LENGTH}:
            selected = (
                AssistantCompletion.NATURAL
                if completion is RunCompletion.NATURAL
                else AssistantCompletion.LENGTH
            )
            self.commit_assistant(assistant_text, selected)
        if usage is not None:
            if not isinstance(usage, Usage):
                raise TypeError("usage 必须是 Provider Usage。")
            self._state.last_usage = usage
        if completion is RunCompletion.NATURAL and lease.mode is RunMode.PLAN:
            self._state.latest_plan = assistant_text
        self._state_store.save(self._state)
        self._leases.pop(lease.id, None)
        self._dispatched.pop(lease.id, None)
        self._projections.pop(lease.id, None)
        return self.snapshot()

    async def compact(
        self, model: Model, trigger: CompactionTrigger
    ) -> CompactionReport:
        self._ensure_open()
        if not isinstance(trigger, CompactionTrigger):
            raise TypeError("trigger 必须是 CompactionTrigger。")
        end = max(self._state.summary_through, len(self._facts) - self._recent_fact_count)
        start = self._state.summary_through
        compactable = sum(
            not isinstance(fact, UserFact) for fact in self._facts[start:end]
        )
        if compactable == 0:
            return CompactionReport(trigger, "noop")
        try:
            summary = await generate_summary(
                model,
                self._facts,
                start=start,
                end=end,
                previous_summary=self._state.summary,
            )
        except asyncio.CancelledError:
            raise
        except BaseException as exc:
            return CompactionReport(trigger, "failed", detail=str(exc))
        if trigger in {CompactionTrigger.AUTOMATIC, CompactionTrigger.EMERGENCY}:
            prefix = (ModelMessage("system", "Transcript projection"),)
            previous_summary = (
                (summary_message(self._state.summary, self._state.summary_through),)
                if self._state.summary else ()
            )
            current = ModelRequest((*prefix, *previous_summary, *project_facts(self._facts, start)))
            candidate = ModelRequest((*prefix, summary_message(summary, end), *project_facts(self._facts, end)))
            if estimate_request(candidate).tokens >= estimate_request(current).tokens:
                return CompactionReport(trigger, "noop", detail="候选摘要没有缩短完整请求。")
        previous = (self._state.summary, self._state.summary_through)
        self._state.summary = summary
        self._state.summary_through = end
        try:
            self._state_store.save(self._state)
        except BaseException as exc:
            self._state.summary, self._state.summary_through = previous
            return CompactionReport(trigger, "failed", detail=str(exc))
        return CompactionReport(trigger, "success", compactable)

    def schedule_memory_update(
        self,
        lease: RunLease,
        completion: RunCompletion,
        assistant_text: str,
        model: Model,
    ) -> bool:
        self._ensure_open()
        if completion is not RunCompletion.NATURAL:
            return False
        if self._leases.get(lease.id) != lease:
            raise ValueError("Memory update 必须使用当前 Session 的不可变 Run lease。")
        self._memory.schedule(lease, assistant_text, model)
        return True

    async def wait_memory_idle(self) -> None:
        await self._memory.wait_idle()

    async def aclose(self) -> None:
        await self._memory.wait_idle()
        self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._memory.cancel()
        if self._lock is not None:
            self._lock.close()
            self._lock = None
        self._closed = True

    def _initialize_derived(self) -> None:
        self._instructions, self._instruction_issues = load_instructions(
            self.workspace, self._user_home
        )
        self._state_store = DerivedStateStore(self._directory / "state.json")
        self._state, state_issues = self._state_store.load()
        if self._state.summary_through > len(self._facts):
            self._state.summary = None
            self._state.summary_through = 0
            state_issues = (*state_issues, "Summary 范围超过 Transcript，已忽略。")
        self._issues = (*self._issues, *state_issues, *self._instruction_issues)
        self._memory = MemoryManager(
            self._user_home / "memory.md",
            self.workspace / ".artcode" / "ch14" / "memory.md",
        )
        self._leases: dict[str, RunLease] = {}
        self._dispatched: dict[str, DispatchedRun] = {}
        self._projections: dict[str, RunProjection] = {}
        if (
            self._restored
            and float(self._clock()) - self._created_at >= self._resume_notice_after_seconds
            and not any("外部环境" in text for _, text in self._state.notices)
        ):
            add_notice(self._state, "Session 间隔较长，请重新核对外部环境和 Workspace 状态。")
            self._state_store.save(self._state)

    def _create(self) -> None:
        created_at = float(self._clock())
        for _ in range(100):
            session_id = new_session_id(created_at)
            directory = self._root / session_id
            try:
                directory.mkdir(mode=0o700)
            except FileExistsError:
                continue
            self._directory = directory
            self._session_id = session_id
            self._created_at = created_at
            self._lock = SessionLock(directory / "write.lock")
            write_metadata(
                directory / "metadata.json",
                session_id=session_id,
                created_at=created_at,
                workspace=self.workspace,
            )
            self.archive_path.touch(mode=0o600)
            self._next_sequence = 1
            self._restored = False
            return
        raise RuntimeError("无法生成唯一 Session ID。")

    def _restore_latest(self) -> bool:
        candidates: list[tuple[float, str]] = []
        for directory in self._root.iterdir():
            if not directory.is_dir() or directory.is_symlink():
                continue
            metadata = read_metadata(directory / "metadata.json", self.workspace)
            if metadata is not None and metadata[0] == directory.name:
                candidates.append((metadata[1], metadata[0]))
        for _, session_id in sorted(candidates, reverse=True):
            try:
                self._restore_exact(session_id)
                return True
            except SessionBusy:
                continue
            except SessionCorrupt:
                continue
        return False

    def _restore_exact(self, session_id: str) -> None:
        directory = self._root / validate_session_id(session_id)
        if directory.is_symlink() or not directory.is_dir():
            raise SessionCorrupt(f"Session 不存在或目录不可信：{session_id}")
        metadata = read_metadata(directory / "metadata.json", self.workspace)
        if metadata is None or metadata[0] != session_id:
            raise SessionCorrupt(f"Session 元数据损坏：{session_id}")
        lock = SessionLock(directory / "write.lock")
        try:
            archive = directory / "transcript.jsonl"
            if archive.is_symlink() or not archive.is_file():
                raise SessionCorrupt(f"Session Transcript 缺失或不可信：{session_id}")
            facts, next_sequence, issues = recover_transcript(archive)
        except BaseException:
            lock.close()
            raise
        self._directory = directory
        self._session_id = session_id
        self._created_at = metadata[1]
        self._lock = lock
        self._facts = facts
        self._next_sequence = next_sequence
        self._issues = issues
        self._restored = True

    def _append(self, fact: TranscriptFact) -> SessionSnapshot:
        self._ensure_open()
        if self._write_failed:
            raise SessionCorrupt("上次同步追加失败，必须重新恢复 Session 后才能继续。")
        data = encode_record(self._next_sequence, fact_payload(fact))
        try:
            append_record(self.archive_path, data)
        except BaseException:
            self._write_failed = True
            raise
        self._facts = (*self._facts, fact)
        self._next_sequence += 1
        return self.snapshot()

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("Session 已关闭。")


__all__ = ["LocalSession"]
