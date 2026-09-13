#!/usr/bin/env python3
"""Audit ch14 module dependencies and cutover residue."""

from __future__ import annotations

import argparse
import ast
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
ARTCODE = ROOT / "artcode"
MODULES = {"application", "session", "agent", "model", "tool", "workspace", "skill", "subagent"}
OLD = {
    "agent", "background", "commands", "context_management", "conversation", "mcp",
    "permissions", "persistence", "prompting", "providers", "runtime", "sandbox",
    "security", "skills", "subagents", "tools", "tui", "worktrees",
}
OLD_FILES = {"bootstrap.py", "config.py", "errors.py", "prompts.py", "workspace.py"}
PRIVATE_ALLOWED = {
    "_application": {"_session", "_agent", "_model", "_tool", "_workspace", "_skill", "_subagent"},
    "_session": set(),
    "_agent": set(),
    "_model": set(),
    "_tool": set(),
    "_workspace": set(),
    "_skill": {"_agent", "_session"},
    "_subagent": {"_agent", "_session"},
}


def imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.append(node.module)
    return result


def audit(stage: str) -> list[str]:
    failures: list[str] = []
    core_files = {path.stem for path in (ARTCODE / "core").glob("*.py") if path.name != "__init__.py"}
    if core_files != MODULES:
        failures.append(f"core Interface files mismatch: {sorted(core_files ^ MODULES)}")
    for package in PRIVATE_ALLOWED:
        if not (ARTCODE / package / "__init__.py").is_file():
            failures.append(f"missing private implementation package: {package}")
    scanned = [
        path
        for root in [ARTCODE / "core", ARTCODE / "adapters", *(ARTCODE / name for name in PRIVATE_ALLOWED)]
        for path in root.rglob("*.py")
    ]
    for path in scanned:
        relative = path.relative_to(ROOT)
        owner = path.relative_to(ARTCODE).parts[0]
        for imported in imports(path):
            parts = imported.split(".")
            if len(parts) >= 2 and parts[0] == "artcode" and parts[1] in OLD:
                failures.append(f"{relative} imports old business module {imported}")
            if imported == "tests" or imported.startswith("tests."):
                failures.append(f"{relative} imports test code {imported}")
            if owner in PRIVATE_ALLOWED and len(parts) >= 2 and parts[0] == "artcode" and parts[1].startswith("_"):
                target = parts[1]
                if target != owner and target not in PRIVATE_ALLOWED[owner]:
                    failures.append(f"{relative} imports disallowed private module {imported}")
            if owner == "core" and len(parts) >= 2 and parts[0] == "artcode" and parts[1].startswith("_"):
                failures.append(f"{relative} exposes private implementation {imported}")
    new_model_text = "\n".join(path.read_text(encoding="utf-8") for path in (ARTCODE / "_model").glob("*.py"))
    if "MAX_STREAM_ATTEMPTS" in new_model_text or "retry" in new_model_text.casefold():
        failures.append("new Model implementation contains transparent retry residue")
    if stage == "T14":
        for name in sorted(OLD):
            if (ARTCODE / name).exists():
                failures.append(f"old package still exists: artcode/{name}")
        for name in sorted(OLD_FILES):
            if (ARTCODE / name).exists():
                failures.append(f"old module still exists: artcode/{name}")
        entry_text = (ARTCODE / "cli.py").read_text(encoding="utf-8")
        if "artcode._application" not in entry_text or "artcode.bootstrap" in entry_text:
            failures.append("CLI entry has not switched exclusively to ch14 Application")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("T13", "T14"), required=True)
    args = parser.parse_args()
    failures = audit(args.stage)
    if failures:
        print("core import audit failed:", *failures, sep="\n- ", file=sys.stderr)
        return 1
    print(f"core import audit valid for {args.stage}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
