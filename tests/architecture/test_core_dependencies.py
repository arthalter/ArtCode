from __future__ import annotations

import ast
from pathlib import Path

from artcode.core import CORE_ARCHITECTURE, CORE_MODULES


ROOT = Path(__file__).resolve().parents[2]
CORE_ROOT = ROOT / "artcode" / "core"
EXPECTED_MODULES = {
    "application", "session", "agent", "model", "tool", "workspace", "skill", "subagent"
}
OLD_BUSINESS_PREFIXES = (
    "artcode.agent",
    "artcode.background",
    "artcode.bootstrap",
    "artcode.commands",
    "artcode.config",
    "artcode.context_management",
    "artcode.conversation",
    "artcode.errors",
    "artcode.mcp",
    "artcode.permissions",
    "artcode.persistence",
    "artcode.prompting",
    "artcode.prompts",
    "artcode.providers",
    "artcode.runtime",
    "artcode.sandbox",
    "artcode.security",
    "artcode.skills",
    "artcode.subagents",
    "artcode.tools",
    "artcode.tui",
    "artcode.workspace",
    "artcode.worktrees",
)
FORBIDDEN_ADAPTER_PREFIXES = ("artcode.adapters", "tests")


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return imports


def _is_prefix(module: str, prefix: str) -> bool:
    return module == prefix or module.startswith(prefix + ".")


def test_architecture_manifest_has_exactly_eight_unique_state_owners() -> None:
    assert set(CORE_MODULES) == EXPECTED_MODULES
    assert set(CORE_ARCHITECTURE) == EXPECTED_MODULES

    ownership: dict[str, str] = {}
    for module, rule in CORE_ARCHITECTURE.items():
        assert rule.owns, f"{module} must own at least one state category"
        assert rule.may_depend_on <= EXPECTED_MODULES - {module}
        for state in rule.owns:
            assert state not in ownership, f"{state} is owned by both {ownership.get(state)} and {module}"
            ownership[state] = module


def test_core_dependency_graph_is_acyclic() -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(module: str) -> None:
        assert module not in visiting, f"core dependency cycle reaches {module}"
        if module in visited:
            return
        visiting.add(module)
        for dependency in CORE_ARCHITECTURE[module].may_depend_on:
            visit(dependency)
        visiting.remove(module)
        visited.add(module)

    for module in CORE_MODULES:
        visit(module)


def test_public_core_never_imports_old_business_or_concrete_adapters() -> None:
    forbidden = OLD_BUSINESS_PREFIXES + FORBIDDEN_ADAPTER_PREFIXES
    violations: list[str] = []
    for path in sorted(CORE_ROOT.glob("*.py")):
        for imported in _imports(path):
            if any(_is_prefix(imported, prefix) for prefix in forbidden):
                violations.append(f"{path.relative_to(ROOT)} imports {imported}")
            if imported.startswith("artcode._"):
                violations.append(f"{path.relative_to(ROOT)} imports private implementation {imported}")
    assert not violations, "\n".join(violations)


def test_core_modules_only_import_allowed_core_interfaces() -> None:
    violations: list[str] = []
    for path in sorted(CORE_ROOT.glob("*.py")):
        owner = path.stem
        if owner not in CORE_ARCHITECTURE:
            continue
        for imported in _imports(path):
            prefix = "artcode.core."
            if imported.startswith(prefix):
                dependency = imported.removeprefix(prefix).split(".", 1)[0]
                if dependency not in CORE_ARCHITECTURE[owner].may_depend_on:
                    violations.append(f"{owner} imports disallowed core module {dependency}")
    assert not violations, "\n".join(violations)
