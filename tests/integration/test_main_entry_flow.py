from __future__ import annotations

import importlib
import importlib.util
import tomllib
from pathlib import Path

import pytest


pytestmark = pytest.mark.ch10_5

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    ("package", "symbol", "implementation"),
    [
        ("artcode.providers", "DeepSeekChatProvider", "artcode.providers.deepseek"),
        ("artcode.providers", "ProviderRequest", "artcode.providers.base"),
        ("artcode.agent", "AgentLoop", "artcode.agent.loop"),
        ("artcode.agent", "RequestPreparer", "artcode.agent.request"),
        ("artcode.tools", "ToolEnvironment", "artcode.tools.base"),
        ("artcode.tools", "ToolRunContext", "artcode.tools.base"),
        ("artcode.persistence", "SessionService", "artcode.persistence.session_service"),
        ("artcode.persistence", "MemoryService", "artcode.persistence.memory_service"),
        ("artcode.persistence", "DurablePromptSource", "artcode.prompting.durable"),
        ("artcode.runtime", "ArtCodeRuntime", "artcode.runtime.app"),
    ],
    ids=(
        "provider",
        "provider-request",
        "agent-loop",
        "request-preparer",
        "tool-environment",
        "tool-run-context",
        "session-service",
        "memory-service",
        "durable-prompt",
        "runtime",
    ),
)
def test_public_symbols_resolve_directly_to_final_implementation(
    package: str,
    symbol: str,
    implementation: str,
) -> None:
    exported = getattr(importlib.import_module(package), symbol)

    assert exported.__module__ == implementation


@pytest.mark.parametrize(
    "module_name",
    [
        "artcode.providers." + "openai" + "_compatible",
        "artcode.agent." + "tools",
        "artcode.persistence." + "coordinator",
    ],
    ids=("provider-compat", "agent-compat", "persistence-compat"),
)
def test_removed_compatibility_modules_have_no_import_spec(module_name: str) -> None:
    # These names intentionally protect the T14 deletion contract.
    assert importlib.util.find_spec(module_name) is None


def test_module_entrypoint_uses_the_cli_main_function() -> None:
    from artcode import __main__
    from artcode.cli import main

    assert __main__.main is main


def test_console_script_and_module_entrypoint_share_one_cli_target() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert project["project"]["scripts"] == {"artcode": "artcode.cli:main"}
