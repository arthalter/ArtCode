from __future__ import annotations

from pathlib import Path

import pytest

from artcode.agent import NORMAL_AGENT_MODE
from artcode.permissions import (
    ApprovalChoice,
    PermissionAction,
    PermissionDecision,
    PermissionSnapshot,
    PermissionState,
    RuleSource,
)
from artcode.permissions.service import PermissionService
from artcode.tools import (
    PreparedToolCall,
    ToolDescriptor,
    ToolEffect,
    ToolEnvironment,
    ToolOrigin,
    ToolPreview,
    ToolRunContext,
)

pytestmark = pytest.mark.ch10_5


class BareTool:
    async def execute(self, prepared, context):
        raise AssertionError("not used")


class Engine:
    def __init__(self, action: PermissionAction) -> None:
        self.action = action
        self.requests = []

    def decide(self, request, state):
        self.requests.append((request, state))
        return PermissionDecision(self.action, RuleSource.MODE, "fixture")


class Approver:
    def __init__(self, value) -> None:
        self.value = value
        self.requests = []

    async def request_approval(self, request):
        self.requests.append(request)
        return self.value

    async def request_mcp_approval(self, preview, plan_mode):
        self.requests.append((preview, plan_mode))
        return self.value


class Writer:
    def __init__(self) -> None:
        self.calls = []

    def write_exact(self, match, action):
        self.calls.append((match, action))


def descriptor(effect: ToolEffect, *, configurable: bool = True) -> ToolDescriptor:
    external = effect is ToolEffect.EXTERNAL
    return ToolDescriptor(
        "mcp_tool" if external else f"tool_{effect.value}",
        "fixture",
        {"type": "object"},
        effect,
        ToolOrigin.MCP if external else ToolOrigin.BUILTIN,
        False if external else configurable,
    )


def prepared(selected: ToolDescriptor, target: str = "target") -> PreparedToolCall:
    arguments = {"command": f"  {target}  "} if selected.effect is ToolEffect.SHELL else {}
    return PreparedToolCall(
        BareTool(),
        arguments,
        ToolPreview(selected.name, "preview", target),
    )


def run_context(tmp_path: Path) -> ToolRunContext:
    return ToolRunContext(
        ToolEnvironment.from_workspace(tmp_path),
        NORMAL_AGENT_MODE,
        PermissionSnapshot(PermissionState().mode, PermissionState().shell_policy),
    )


@pytest.mark.parametrize(
    "effect",
    [ToolEffect.READ, ToolEffect.WRITE, ToolEffect.SHELL, ToolEffect.EXTERNAL],
    ids=("read", "write", "shell", "external"),
)
async def test_service_without_engine_allows_builtins_but_mcp_still_asks(tmp_path, effect) -> None:
    selected = descriptor(effect)
    approver = Approver(True)
    service = PermissionService(PermissionState(), approver=approver)

    result = await service.authorize(selected, prepared(selected), run_context(tmp_path))

    assert result is None
    assert bool(approver.requests) is (effect is ToolEffect.EXTERNAL)


@pytest.mark.parametrize(
    ("action", "expected"),
    [(PermissionAction.ALLOW, None), (PermissionAction.DENY, "permission_denied")],
    ids=("allow", "deny"),
)
async def test_engine_terminal_decision_skips_approval(tmp_path, action, expected) -> None:
    selected = descriptor(ToolEffect.WRITE)
    approver = Approver(ApprovalChoice.ALLOW_ONCE)
    service = PermissionService(PermissionState(), engine=Engine(action), approver=approver)

    result = await service.authorize(selected, prepared(selected), run_context(tmp_path))

    assert (None if result is None else result.error_code) == expected
    assert not approver.requests


@pytest.mark.parametrize(
    ("choice", "allowed"),
    [
        (ApprovalChoice.ALLOW_ONCE, True),
        (ApprovalChoice.DENY_ONCE, False),
        (ApprovalChoice.ALLOW_ALWAYS, True),
        (ApprovalChoice.DENY_ALWAYS, False),
    ],
    ids=("allow-once", "deny-once", "allow-always", "deny-always"),
)
async def test_four_user_choices_keep_visible_semantics(tmp_path, choice, allowed) -> None:
    selected = descriptor(ToolEffect.WRITE)
    writer = Writer()
    service = PermissionService(
        PermissionState(),
        engine=Engine(PermissionAction.ASK),
        approver=Approver(choice),
        rule_writer=writer,
    )

    result = await service.authorize(selected, prepared(selected), run_context(tmp_path))

    assert (result is None) is allowed
    assert bool(writer.calls) is choice.value.endswith("always")


@pytest.mark.parametrize(
    ("choice", "action"),
    [
        (ApprovalChoice.ALLOW_ALWAYS, PermissionAction.ALLOW),
        (ApprovalChoice.DENY_ALWAYS, PermissionAction.DENY),
    ],
    ids=("persist-allow", "persist-deny"),
)
async def test_permanent_choice_writes_exact_escaped_rule(tmp_path, choice, action) -> None:
    selected = descriptor(ToolEffect.WRITE)
    writer = Writer()
    service = PermissionService(
        PermissionState(),
        engine=Engine(PermissionAction.ASK),
        approver=Approver(choice),
        rule_writer=writer,
    )

    await service.authorize(selected, prepared(selected, "a*[b]?.txt"), run_context(tmp_path))

    assert writer.calls == [("tool_write(a\\*\\[b]\\?.txt)", action)]


@pytest.mark.parametrize(
    "choice",
    [ApprovalChoice.ALLOW_ALWAYS, ApprovalChoice.DENY_ALWAYS],
    ids=("nonconfig-allow", "nonconfig-deny"),
)
async def test_nonconfigurable_builtin_rejects_permanent_choice(tmp_path, choice) -> None:
    selected = descriptor(ToolEffect.WRITE, configurable=False)
    service = PermissionService(
        PermissionState(),
        engine=Engine(PermissionAction.ASK),
        approver=Approver(choice),
        rule_writer=Writer(),
    )

    result = await service.authorize(selected, prepared(selected), run_context(tmp_path))

    assert result.error_code == "permission_rule_error"


@pytest.mark.parametrize("effect", [ToolEffect.WRITE, ToolEffect.EXTERNAL], ids=("builtin", "mcp"))
async def test_missing_approver_returns_permission_required(tmp_path, effect) -> None:
    selected = descriptor(effect)
    service = PermissionService(
        PermissionState(),
        engine=Engine(PermissionAction.ASK) if effect is not ToolEffect.EXTERNAL else None,
    )

    result = await service.authorize(selected, prepared(selected), run_context(tmp_path))

    assert result.error_code == "permission_required"


@pytest.mark.parametrize("approved", [True, False], ids=("mcp-allow", "mcp-deny"))
async def test_mcp_is_confirmed_once_and_never_persisted(tmp_path, approved) -> None:
    selected = descriptor(ToolEffect.EXTERNAL)
    approver = Approver(approved)
    writer = Writer()
    service = PermissionService(PermissionState(), approver=approver, rule_writer=writer)

    result = await service.authorize(selected, prepared(selected), run_context(tmp_path))

    assert (result is None) is approved
    assert len(approver.requests) == 1
    assert not writer.calls


@pytest.mark.parametrize("effect", [ToolEffect.WRITE, ToolEffect.EXTERNAL], ids=("builtin", "mcp"))
async def test_invalid_approval_response_is_structured_error(tmp_path, effect) -> None:
    selected = descriptor(effect)
    service = PermissionService(
        PermissionState(),
        engine=Engine(PermissionAction.ASK) if effect is not ToolEffect.EXTERNAL else None,
        approver=Approver("yes"),
    )

    result = await service.authorize(selected, prepared(selected), run_context(tmp_path))

    assert result.error_code == "permission_approval_error"


@pytest.mark.parametrize("failure", [RuntimeError, ValueError])
async def test_engine_failure_is_structured(tmp_path, failure) -> None:
    class FailingEngine:
        def decide(self, request, state):
            raise failure("bad rules")

    selected = descriptor(ToolEffect.WRITE)
    result = await PermissionService(PermissionState(), engine=FailingEngine()).authorize(
        selected, prepared(selected), run_context(tmp_path)
    )
    assert result.error_code == "permission_rule_error"


@pytest.mark.parametrize("effect", [ToolEffect.WRITE, ToolEffect.EXTERNAL])
async def test_approval_failure_is_structured(tmp_path, effect) -> None:
    class FailingApprover(Approver):
        async def request_approval(self, request):
            raise RuntimeError("ui failed")

        async def request_mcp_approval(self, preview, plan_mode):
            raise RuntimeError("ui failed")

    selected = descriptor(effect)
    service = PermissionService(
        PermissionState(),
        engine=Engine(PermissionAction.ASK) if effect is ToolEffect.WRITE else None,
        approver=FailingApprover(None),
    )
    result = await service.authorize(selected, prepared(selected), run_context(tmp_path))
    assert result.error_code == "permission_approval_error"


async def test_permanent_choice_requires_writer(tmp_path) -> None:
    selected = descriptor(ToolEffect.WRITE)
    service = PermissionService(
        PermissionState(),
        engine=Engine(PermissionAction.ASK),
        approver=Approver(ApprovalChoice.ALLOW_ALWAYS),
    )
    result = await service.authorize(selected, prepared(selected), run_context(tmp_path))
    assert result.error_code == "permission_rule_error"
    assert "写入器" in result.message


async def test_rule_writer_failure_is_structured(tmp_path) -> None:
    class FailingWriter:
        def write_exact(self, match, action):
            raise OSError("read only")

    selected = descriptor(ToolEffect.WRITE)
    service = PermissionService(
        PermissionState(),
        engine=Engine(PermissionAction.ASK),
        approver=Approver(ApprovalChoice.DENY_ALWAYS),
        rule_writer=FailingWriter(),
    )
    result = await service.authorize(selected, prepared(selected), run_context(tmp_path))
    assert result.error_code == "permission_rule_error"
