from __future__ import annotations

from artcode.agent import AgentEventType

from .models import SubagentResult, SubagentStopReason, UsageTotals
from .runtime import SubagentRuntime


class RunToCompletion:
    async def run(self, runtime: SubagentRuntime, request) -> SubagentResult:
        text = ""
        rounds = 0
        usage = UsageTotals.empty()
        reason = SubagentStopReason.FAILED
        error = ""
        handoff = None
        try:
            async for event in runtime.loop.run(request):
                if event.type is AgentEventType.ITERATION_STARTED:
                    rounds = event.payload["current"]
                elif event.type is AgentEventType.MODEL_TURN_COMPLETED:
                    if event.payload.get("text"):
                        text = event.payload["text"]
                elif event.type is AgentEventType.TOKEN_USAGE:
                    from artcode.providers.events import TokenUsage
                    usage = usage.add(TokenUsage.from_event_payload(event.payload))
                elif event.type is AgentEventType.STOPPED:
                    stopped = event.payload["reason"]
                    if stopped == "natural":
                        reason = SubagentStopReason.NATURAL
                    elif stopped == "iteration_limit":
                        reason = SubagentStopReason.MAX_ROUNDS
                    elif stopped == "user_cancelled":
                        reason = SubagentStopReason.CANCELLED
                    else:
                        reason = SubagentStopReason.FAILED
                        error = event.payload.get("message", "")
        except BaseException as exc:
            import asyncio
            if isinstance(exc, asyncio.CancelledError):
                reason = SubagentStopReason.CANCELLED
            else:
                reason = SubagentStopReason.FAILED
                error = str(exc)
        finally:
            if runtime.close is not None:
                try:
                    runtime.close()
                except Exception as exc:
                    if error:
                        error = f"{error}; 子 Agent 资源关闭失败：{exc}"
                    else:
                        error = f"子 Agent 资源关闭失败：{exc}"
                    if reason is SubagentStopReason.NATURAL:
                        reason = SubagentStopReason.FAILED
            if runtime.worktree_lease is not None:
                handoff = self._handoff(runtime)
        return SubagentResult(
            task_id=runtime.task_id,
            stop_reason=reason,
            final_text=text,
            rounds=rounds,
            usage=usage,
            permission_events=tuple(runtime.permissions.events),
            handoff=handoff,
            error_message=error,
            cache_prefix_preserved=(
                getattr(runtime, "_request_preparer").initial_cache_prefix_preserved
                if hasattr(runtime, "_request_preparer")
                else None
            ),
        )

    @staticmethod
    def _handoff(runtime: SubagentRuntime):
        try:
            from artcode.worktrees import WorktreeManager
            # The factory attaches the manager to the lease's main workspace;
            # runtime has no global mutable cwd to recover from here.
            manager = getattr(runtime, "_worktree_manager", None)
            if manager is None:
                manager = WorktreeManager(runtime.worktree_lease.main_workspace)
            return manager.handoff(runtime.worktree_lease)
        except Exception as exc:
            lease = runtime.worktree_lease
            from artcode.worktrees.models import WorktreeHandoff
            return WorktreeHandoff(
                lease.baseline, lease.branch, lease.path, True, 0, 0, 0, 0, False, False,
                f"无法完成 Worktree 交接检查，已保留：{exc}",
            )
