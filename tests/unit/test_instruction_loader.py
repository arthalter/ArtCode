from __future__ import annotations

from pathlib import Path

from artcode.persistence import DurablePaths, InstructionLoader, InstructionScope
from artcode.workspace import ArtCodePaths, Workspace


def _paths(tmp_path: Path) -> DurablePaths:
    project = tmp_path / "project"
    project.mkdir()
    return DurablePaths.from_context(
        ArtCodePaths.create(tmp_path / "home"), Workspace.from_path(project)
    )


def test_instruction_loader_orders_layers_and_expands_include(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    include = paths.project_instruction.parent / "rules" / "python.md"
    include.parent.mkdir()
    include.write_text("Python 3.11\n", encoding="utf-8")
    paths.local_instruction.parent.mkdir(exist_ok=True)
    paths.local_instruction.write_text("local\n", encoding="utf-8")
    paths.project_instruction.write_text(
        "root\n@include rules/python.md\n```md\n@include missing.md\n```\nend\n",
        encoding="utf-8",
    )
    paths.user_instruction.write_text("user\n", encoding="utf-8")

    bundle = InstructionLoader(paths).load()

    assert [item.scope for item in bundle.documents] == [
        InstructionScope.PROJECT_LOCAL,
        InstructionScope.PROJECT_ROOT,
        InstructionScope.USER,
    ]
    assert bundle.documents[1].content == (
        "root\nPython 3.11\n```md\n@include missing.md\n```\nend\n"
    )
    assert bundle.documents[1].included_paths == (include.resolve(),)
    assert not bundle.issues


def test_instruction_loader_isolates_unsafe_and_cyclic_includes(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    outside = tmp_path / "outside.md"
    outside.write_text("secret", encoding="utf-8")
    child = paths.project_instruction.parent / "child.md"
    paths.project_instruction.write_text(
        "ok\n@include child.md\n@include ../outside.md\n@include /tmp/no.md\n@include child.txt\n",
        encoding="utf-8",
    )
    child.write_text("child\n@include ARTCODE.md\n", encoding="utf-8")

    bundle = InstructionLoader(paths).load()

    assert bundle.documents[0].content == "ok\nchild\n"
    codes = {issue.code for issue in bundle.issues}
    assert {"include_cycle", "include_outside", "invalid_include"} <= codes


def test_instruction_loader_enforces_depth_and_utf8_budget(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    current = paths.project_instruction
    for index in range(1, 8):
        next_path = current.parent / f"level-{index}.md"
        current.write_text(f"L{index - 1}\n@include {next_path.name}\n", encoding="utf-8")
        current = next_path
    current.write_text("too-deep\n", encoding="utf-8")
    paths.local_instruction.parent.mkdir(exist_ok=True)
    paths.local_instruction.write_text("高优先级\n", encoding="utf-8")
    paths.user_instruction.write_text("低优先级\n" * 10, encoding="utf-8")

    bundle = InstructionLoader(paths, budget_bytes=80).load()

    assert bundle.total_bytes <= 80
    assert bundle.documents[0].scope is InstructionScope.PROJECT_LOCAL
    assert bundle.documents[0].content.encode("utf-8").decode("utf-8")
    assert any(issue.code == "include_depth" for issue in bundle.issues)
    assert any(issue.code.startswith("budget_") for issue in bundle.issues)


def test_instruction_loader_skips_bad_utf8_without_blocking_other_layers(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    paths.project_instruction.write_bytes(b"\xff\xfe")
    paths.user_instruction.write_text("still loaded\n", encoding="utf-8")

    bundle = InstructionLoader(paths).load()

    assert [item.scope for item in bundle.documents] == [InstructionScope.USER]
    assert any(issue.code == "invalid_utf8" for issue in bundle.issues)
