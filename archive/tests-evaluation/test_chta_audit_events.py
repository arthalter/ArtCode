from __future__ import annotations

from pathlib import Path

from artcode.agent import NORMAL_AGENT_MODE, AgentEventType, RequestPreparer
from artcode.conversation import ConversationContext
from artcode.evaluation.redaction import Redactor
from artcode.evaluation.trace import RunTraceRecorder
from artcode.permissions import (
    ApprovalChoice,
    PermissionEngine,
    PermissionState,
    RuleLoader,
    RulePaths,
    RuleWriter,
)
from artcode.permissions.service import PermissionService
from artcode.prompting.assembler import PromptRequestAssembler
from artcode.security import DangerousCommandValidator
from artcode.tools import ToolEnvironment, create_default_tool_registry
from artcode.tools.execution import ToolExecutionService
from artcode.providers.tool_calls import ToolCall


class AlwaysApprover:
    async def request_approval(self, request):
        return ApprovalChoice.ALLOW_ALWAYS


async def test_request_and_permission_audit_are_evidence_without_raw_target(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    registry = create_default_tool_registry()
    environment = ToolEnvironment.from_workspace(workspace)
    state = PermissionState()
    recorder = RunTraceRecorder(
        tmp_path / "trace.jsonl",
        run_id="audit",
        task_id="audit",
        attempt=1,
        redactor=Redactor(),
    )
    recorder.start()

    preparer = RequestPreparer(
        ConversationContext(),
        PromptRequestAssembler(),
        registry,
        environment,
        state,
    )
    prepared = await preparer.prepare(NORMAL_AGENT_MODE)
    for event in prepared.events:
        recorder.record_agent_event(event)

    paths = RulePaths(tmp_path / "user.yml", tmp_path / "project.yml", tmp_path / "local.yml")
    rules = RuleLoader(paths)
    permission = PermissionService(
        state,
        engine=PermissionEngine(rules, DangerousCommandValidator.load()),
        approver=AlwaysApprover(),
        rule_writer=RuleWriter(rules),
        audit_sink=recorder.record_agent_event,
    )
    executor = ToolExecutionService(registry, environment, permission)
    plan = executor.build_plan(
        [ToolCall("one", "write_file", '{"path":"private-note.txt","content":"ok"}')],
        NORMAL_AGENT_MODE.tool_policy,
    )
    _ = [event async for event in executor.execute_plan(plan, mode=NORMAL_AGENT_MODE)]
    recorder.finish({"status": "passed"})

    request = next(item for item in recorder.records if item.kind == "model_request")
    assert request.payload["tool_count"] == 6
    assert request.payload["tool_definition_bytes"] > 0
    assert request.payload["tool_definition_tokens"] > 0
    assert request.payload["tokenizer"] == "utf8_regex_v1"

    audit = [item for item in recorder.records if item.kind == "permission_audit"]
    assert [item.payload["event"] for item in audit] == [
        "decision",
        "approval_requested",
        "approval_choice",
        "rule_written",
    ]
    assert all(len(item.payload["target_sha256"]) == 64 for item in audit)
    assert "private-note.txt" not in recorder.path.read_text(encoding="utf-8")


async def test_exact_rule_reuse_emits_rule_hit_without_second_approval(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    registry = create_default_tool_registry()
    environment = ToolEnvironment.from_workspace(workspace)
    state = PermissionState()
    events = []
    paths = RulePaths(tmp_path / "user.yml", tmp_path / "project.yml", tmp_path / "local.yml")
    rules = RuleLoader(paths)
    service = PermissionService(
        state,
        engine=PermissionEngine(rules, DangerousCommandValidator.load()),
        approver=AlwaysApprover(),
        rule_writer=RuleWriter(rules),
        audit_sink=events.append,
    )
    executor = ToolExecutionService(registry, environment, service)
    calls = [
        ToolCall("one", "write_file", '{"path":"same.txt","content":"one"}'),
        ToolCall(
            "two",
            "write_file",
            '{"path":"same.txt","content":"two","overwrite":true}',
        ),
    ]
    for call in calls:
        plan = executor.build_plan([call], NORMAL_AGENT_MODE.tool_policy)
        _ = [event async for event in executor.execute_plan(plan, mode=NORMAL_AGENT_MODE)]

    audit = [event for event in events if event.type is AgentEventType.PERMISSION_AUDIT]
    assert sum(event.payload["event"] == "approval_requested" for event in audit) == 1
    decisions = [event for event in audit if event.payload["event"] == "decision"]
    assert decisions[-1].payload["persistent_rule_hit"] is True
