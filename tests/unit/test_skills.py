from __future__ import annotations

from pathlib import Path

import pytest

from artcode.agent import NORMAL_AGENT_MODE, PLAN_MODE, RequestPreparer
from artcode.commands import create_default_registry
from artcode.conversation import ConversationContext
from artcode.permissions import PermissionState
from artcode.prompting.assembler import PromptRequestAssembler
from artcode.skills import LoadSkillTool, SkillService, SkillStartupError
from artcode.tools import ToolEnvironment, create_default_tool_registry


def test_discovery_is_deterministic_and_project_overrides_user(tmp_path: Path) -> None:
    project, user, builtin = _roots(tmp_path)
    _write_skill(user / "review.md", "review", "User review.", "user SOP")
    _write_skill(project / "review.md", "review", "Project review.", "project SOP")
    _write_skill(builtin / "summarize.md", "summarize", "Summarize work.", "builtin SOP")

    service = _service(project, user, builtin)
    service.start()

    assert service.catalog.names == ("review", "summarize")
    assert service.catalog.get("review").sop == "project SOP"
    assert service.catalog.get("summarize").source.value == "builtin"


def test_bad_candidate_is_diagnostic_without_hiding_valid_skill(tmp_path: Path) -> None:
    project, user, builtin = _roots(tmp_path)
    (project / "broken.md").write_text("not a skill", encoding="utf-8")
    _write_skill(project / "valid.md", "valid", "A valid skill.", "safe SOP")

    service = _service(project, user, builtin)
    service.start()

    assert service.catalog.names == ("valid",)
    assert any(issue.path.name == "broken.md" for issue in service.diagnostics)


def test_directory_skill_has_one_entry_and_never_discovers_its_resources(tmp_path: Path) -> None:
    project, user, builtin = _roots(tmp_path)
    package = project / "package"
    package.mkdir()
    _write_skill(package / "SKILL.md", "package", "Use the package.", "ENTRY SOP")
    (package / "template.md").write_text("TEMPLATE UNIQUE", encoding="utf-8")
    (package / "example.md").write_text("EXAMPLE UNIQUE", encoding="utf-8")
    (package / "helper.py").write_text("raise RuntimeError('must not execute')", encoding="utf-8")

    service = _service(project, user, builtin)
    service.start()
    definition = service.catalog.get("package")

    assert service.catalog.names == ("package",)
    assert definition is not None
    assert definition.sop == "ENTRY SOP"
    assert {item.name for item in definition.resources} == {"SKILL.md", "template.md", "example.md", "helper.py"}


def test_unknown_tool_and_same_source_duplicate_block_cold_start(tmp_path: Path) -> None:
    project, user, builtin = _roots(tmp_path)
    _write_skill(project / "unknown.md", "unknown", "Unknown tool.", "SOP", tools=["missing"])
    with pytest.raises(SkillStartupError, match="未知普通工具"):
        _service(project, user, builtin).start()

    (project / "unknown.md").unlink()
    _write_skill(project / "first.md", "same", "First.", "first")
    _write_skill(project / "second.md", "same", "Second.", "second")
    with pytest.raises(SkillStartupError, match="重复 Skill 名称"):
        _service(project, user, builtin).start()


def test_request_has_only_directory_before_activation_then_sop_and_intersection(tmp_path: Path) -> None:
    project, user, builtin = _roots(tmp_path)
    _write_skill(project / "read.md", "read", "Read only.", "UNIQUE READ SOP", tools=["read_file", "find_files"])
    _write_skill(project / "search.md", "search", "Search only.", "UNIQUE SEARCH SOP", tools=["read_file", "search_text"])
    registry = create_default_tool_registry()
    service = SkillService.from_paths(
        project,
        user,
        builtin,
        known_tool_names={item.name for item in registry.descriptors()},
        reserved_commands={item.name for item in create_default_registry().definitions()},
    )
    service.start()
    registry.register(LoadSkillTool(service))
    preparer = RequestPreparer(
        ConversationContext(),
        PromptRequestAssembler(),
        registry,
        ToolEnvironment.from_workspace(tmp_path),
        PermissionState(),
        skill_service=service,
    )

    initial = preparer.preview_request(NORMAL_AGENT_MODE)
    initial_text = "\n".join(str(message.get("content", "")) for message in initial.messages)
    assert "read: Read only." in initial_text
    assert "UNIQUE READ SOP" not in initial_text
    assert _tool_names(initial) == {
        "read_file", "write_file", "edit_file", "run_command", "find_files", "search_text", "load_skill"
    }

    assert service.activate("read").ok
    one_active = preparer.preview_request(NORMAL_AGENT_MODE)
    assert "UNIQUE READ SOP" in "\n".join(str(message.get("content", "")) for message in one_active.messages)
    assert _tool_names(one_active) == {"read_file", "find_files", "load_skill"}

    assert service.activate("search").ok
    two_active = preparer.preview_request(NORMAL_AGENT_MODE)
    assert _tool_names(two_active) == {"read_file", "load_skill"}
    assert _tool_names(preparer.preview_request(PLAN_MODE)) == {"read_file", "load_skill"}


def test_hot_reload_keeps_last_active_definition_after_bad_edit(tmp_path: Path) -> None:
    project, user, builtin = _roots(tmp_path)
    path = project / "review.md"
    _write_skill(path, "review", "Review changes.", "LAST GOOD SOP")
    service = _service(project, user, builtin)
    service.start()
    assert service.activate("review").ok
    path.write_text("---\nname: review\n---\nbroken", encoding="utf-8")

    snapshot = service.refresh()

    assert snapshot.active_definitions[0].sop == "LAST GOOD SOP"
    assert any("最后有效版本" in item.message for item in service.diagnostics)


def test_name_conflicting_with_static_command_is_rejected_without_breaking_catalog(tmp_path: Path) -> None:
    project, user, builtin = _roots(tmp_path)
    _write_skill(project / "help.md", "help", "Should conflict.", "bad")
    _write_skill(project / "safe.md", "safe", "Safe skill.", "good")

    service = _service(project, user, builtin)
    service.start()

    assert service.catalog.names == ("safe",)
    assert any("内置命令" in item.message for item in service.diagnostics)


def _roots(tmp_path: Path) -> tuple[Path, Path, Path]:
    result = tuple(tmp_path / name for name in ("project", "user", "builtin"))
    for root in result:
        root.mkdir()
    return result  # type: ignore[return-value]


def _service(project: Path, user: Path, builtin: Path) -> SkillService:
    return SkillService.from_paths(
        project,
        user,
        builtin,
        known_tool_names={"read_file", "find_files", "search_text"},
        reserved_commands={item.name for item in create_default_registry().definitions()},
    )


def _write_skill(
    path: Path,
    name: str,
    description: str,
    sop: str,
    *,
    tools: list[str] | None = None,
) -> None:
    path.write_text(
        "\n".join(
            (
                "---",
                f"name: {name}",
                f"description: {description}",
                "tools: [" + ", ".join(tools or ["read_file"]) + "]",
                "mode: shared",
                "---",
                sop,
            )
        ),
        encoding="utf-8",
    )


def _tool_names(request) -> set[str]:
    return {tool["function"]["name"] for tool in request.tools or ()}
