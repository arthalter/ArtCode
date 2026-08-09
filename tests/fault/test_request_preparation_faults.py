from __future__ import annotations

import pytest

from artcode.agent import AgentLoop, AgentRunRequest, NORMAL_AGENT_MODE, RequestPreparer, StopReason
from artcode.context_management.models import CompressionCircuit, CompressionTrigger, LightweightReport
from artcode.conversation import ConversationContext
from artcode.prompting.assembler import PromptRequestAssembler
from artcode.permissions import PermissionState
from artcode.permissions.service import PermissionService
from artcode.tools import ToolEnvironment, ToolRegistry
from artcode.tools.execution import ToolExecutionService

pytestmark = [pytest.mark.ch10_5, pytest.mark.fault]


class NeverProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def stream(self, request):
        self.calls += 1
        if False:
            yield None


class FaultyDurableSource:
    def build_system_prompt(self) -> str:
        raise OSError("durable read failed")


class FaultyAssembler(PromptRequestAssembler):
    def assemble(self, *args, **kwargs):
        raise RuntimeError("assembly failed")


class FaultyContextManager:
    def __init__(self, stage: str) -> None:
        self.stage = stage
        self.circuit = CompressionCircuit()

    def run_lightweight(self, conversation):
        if self.stage == "lightweight":
            raise OSError("artifact persistence failed")
        return LightweightReport()

    def estimate_request(self, request):
        if self.stage == "estimate":
            raise RuntimeError("estimate failed")
        return 100

    def unsafe_persistence_failure(self, conversation, estimated):
        return False

    def choose_trigger(self, estimated):
        return CompressionTrigger.AUTOMATIC if self.stage == "compact" else None

    async def compact(self, conversation, trigger):
        raise OSError("summary commit failed")

    def record_usage(self, usage, request):
        return None


@pytest.mark.parametrize(
    "stage",
    ["durable", "assembler", "lightweight", "estimate", "compact"],
    ids=("durable-source", "assembler", "lightweight", "estimator", "compression"),
)
async def test_every_pre_dispatch_preparation_fault_preserves_resume_reminder(tmp_path, stage: str) -> None:
    conversation = ConversationContext()
    registry = ToolRegistry()
    environment = ToolEnvironment.from_workspace(tmp_path)
    permission = PermissionState()
    provider = NeverProvider()
    preparer = RequestPreparer(
        conversation,
        FaultyAssembler() if stage == "assembler" else PromptRequestAssembler(),
        registry,
        environment,
        permission,
        context_manager=(
            FaultyContextManager(stage)
            if stage in {"lightweight", "estimate", "compact"}
            else None
        ),
        durable_prompt=FaultyDurableSource() if stage == "durable" else None,
        resume_reminder_required=True,
    )
    loop = AgentLoop(
        provider,
        conversation,
        registry,
        environment,
        tool_executor=ToolExecutionService(
            registry,
            environment,
            PermissionService(permission),
        ),
        request_preparer=preparer,
    )

    events = [
        event
        async for event in loop.run(AgentRunRequest("continue", NORMAL_AGENT_MODE))
    ]

    assert events[-1].payload["reason"] == StopReason.STREAM_ERROR.value
    assert provider.calls == 0
    assert preparer.resume_reminder_pending
