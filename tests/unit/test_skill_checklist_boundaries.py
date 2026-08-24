from __future__ import annotations

from pathlib import Path

import pytest

from artcode.agent import NORMAL_AGENT_MODE
from artcode.commands import create_default_registry
from artcode.permissions import PermissionState
from artcode.skills import LoadSkillTool, SkillService
from artcode.tools import ToolEnvironment, ToolRunContext, create_default_tool_registry


def test_frontmatter_rejects_every_unknown_field_with_path_diagnostic(tmp_path: Path) -> None:
    project, user, builtin = _roots(tmp_path)
    for field in ("extra", "unknown", "version"):
        _write_skill(project / f"{field}.md", name=field, extra=f"{field}: value")
    _write_skill(project / "valid.md", name="valid")

    service = _service(project, user, builtin)
    service.start()

    assert service.catalog.names == ("valid",)
    assert {item.path.name for item in service.diagnostics} == {"extra.md", "unknown.md", "version.md"}
    assert all("未知字段" in item.message for item in service.diagnostics)


@pytest.mark.parametrize("name", ("Upper", "has space", "", "-leading", "under_score", "slash/name"))
def test_invalid_skill_names_are_diagnostic_and_do_not_enter_catalog(tmp_path: Path, name: str) -> None:
    project, user, builtin = _roots(tmp_path)
    _write_skill(project / "invalid.md", name=name)
    _write_skill(project / "valid.md", name="valid")

    service = _service(project, user, builtin)
    service.start()

    assert service.catalog.names == ("valid",)
    assert any("Skill name" in item.message for item in service.diagnostics)


@pytest.mark.parametrize(
    ("description", "tools", "expected"),
    (
        ("", "[read_file]", "description"),
        ("Valid description.", "read_file", "tools"),
        ("Valid description.", "[read_file, read_file]", "重复工具名"),
        ("Valid description.", "[read_file, '']", "tools"),
    ),
)
def test_description_and_tools_validation(tmp_path: Path, description: str, tools: str, expected: str) -> None:
    project, user, builtin = _roots(tmp_path)
    _write_skill(project / "invalid.md", description=description, tools=tools)

    service = _service(project, user, builtin)
    service.start()

    assert service.catalog.names == ()
    assert any(expected in item.message for item in service.diagnostics)


def test_multiline_description_is_rejected(tmp_path: Path) -> None:
    project, user, builtin = _roots(tmp_path)
    (project / "invalid.md").write_text(
        "---\n"
        "name: invalid\n"
        "description: |-\n"
        "  first line\n"
        "  second line\n"
        "tools: [read_file]\n"
        "mode: shared\n"
        "---\n"
        "SOP\n",
        encoding="utf-8",
    )

    service = _service(project, user, builtin)
    service.start()

    assert service.catalog.names == ()
    assert any("description" in item.message for item in service.diagnostics)


def test_isolated_history_and_model_metadata_are_validated(tmp_path: Path) -> None:
    project, user, builtin = _roots(tmp_path)
    _write_skill(project / "zero.md", name="zero", mode="isolated")
    _write_skill(project / "history.md", name="history", mode="isolated", extra="history_turns: 2\nmodel: specialist")
    _write_skill(project / "shared-history.md", name="shared-history", extra="history_turns: 1")
    _write_skill(project / "negative.md", name="negative", mode="isolated", extra="history_turns: -1")
    _write_skill(project / "bad-mode.md", name="bad-mode", mode="other")
    _write_skill(project / "empty-model.md", name="empty-model", extra="model: ' '")
    _write_skill(project / "number-model.md", name="number-model", extra="model: 42")

    service = _service(project, user, builtin)
    service.start()

    zero = service.catalog.get("zero")
    history = service.catalog.get("history")
    assert zero is not None and zero.metadata.history_turns == 0 and zero.metadata.model is None
    assert history is not None and history.metadata.history_turns == 2 and history.metadata.model == "specialist"
    messages = "\n".join(item.message for item in service.diagnostics)
    assert "共享 Skill 不支持 history_turns" in messages
    assert "非负整数" in messages
    assert "shared 或 isolated" in messages
    assert "model 必须是非空文本" in messages


def test_sop_is_preserved_verbatim_without_template_expansion(tmp_path: Path) -> None:
    project, user, builtin = _roots(tmp_path)
    sop = "Keep {{input}} and ${HOME} unchanged."
    _write_skill(project / "literal.md", name="literal", sop=sop)

    service = _service(project, user, builtin)
    service.start()
    outcome = service.activate("literal")

    assert outcome.definition is not None
    assert outcome.definition.sop == sop


def test_bad_utf8_unreadable_and_symlink_candidates_do_not_hide_valid_skill(tmp_path: Path, monkeypatch) -> None:
    project, user, builtin = _roots(tmp_path)
    (project / "bad.md").write_bytes(b"---\nname: bad\n\xff")
    _write_skill(project / "denied.md", name="denied")
    _write_skill(project / "valid.md", name="valid")
    target = project / "target.md"
    _write_skill(target, name="target")
    package = project / "escaped-package"
    package.mkdir()
    _write_skill(package / "SKILL.md", name="escaped")
    outside_resource = tmp_path / "outside-resource.txt"
    outside_resource.write_text("outside", encoding="utf-8")
    try:
        (project / "link.md").symlink_to(target)
        (package / "outside-link.txt").symlink_to(outside_resource)
    except OSError:
        pytest.skip("filesystem does not allow symlink test")

    real_read_text = Path.read_text

    def denied_read_text(path: Path, *args, **kwargs):
        if path.name == "denied.md":
            raise PermissionError("simulated unreadable skill")
        return real_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", denied_read_text)

    service = _service(project, user, builtin)
    service.start()

    assert service.catalog.names == ("target", "valid")
    messages = "\n".join(item.message for item in service.diagnostics)
    assert "UTF-8" in messages
    assert "无法读取 Skill 文件" in messages
    assert "符号链接" in messages


def test_load_skill_rejects_paths_unknown_values_and_keeps_activation_unchanged(tmp_path: Path) -> None:
    project, user, builtin = _roots(tmp_path)
    _write_skill(project / "valid.md", name="valid")
    service = _service(project, user, builtin)
    service.start()
    tool = LoadSkillTool(service)
    context = ToolRunContext(
        ToolEnvironment.from_workspace(tmp_path),
        NORMAL_AGENT_MODE,
        PermissionState().snapshot(),
    )

    for arguments in ({}, {"name": ".."}, {"name": "folder/name"}, {"name": "missing"}, {"name": "valid", "extra": 1}):
        prepared = tool.prepare(arguments, context)
        if hasattr(prepared, "error_code"):
            assert prepared.error_code == "invalid_arguments"
            continue
        result = asyncio_run(tool.execute(prepared, context))
        assert result.error_code == "skill_not_found"
    assert service.snapshot().active == ()


def test_refresh_preserves_order_updates_valid_changes_retains_deleted_and_clear_resets_state(tmp_path: Path) -> None:
    project, user, builtin = _roots(tmp_path)
    first = project / "first.md"
    second = project / "second.md"
    _write_skill(first, name="first", sop="FIRST v1")
    _write_skill(second, name="second", sop="SECOND", extra="model: specialist")
    service = _service(project, user, builtin)
    service.start()
    assert service.activate("second", for_model_execution=True).ok
    assert service.consume_model_override() == "specialist"
    assert service.activate("second", for_model_execution=True).ok
    assert service.activate("first").ok

    _write_skill(first, name="first", sop="FIRST v2")
    refreshed = service.refresh()
    assert [item.definition.name for item in refreshed.active] == ["second", "first"]
    assert refreshed.active_definitions[1].sop == "FIRST v2"

    second.unlink()
    refreshed = service.refresh()
    assert service.catalog.get("second") is None
    assert [item.definition.name for item in refreshed.active] == ["second", "first"]
    assert any("已删除" in item.message for item in service.diagnostics)

    service.clear()
    assert service.snapshot().active == ()
    assert service.consume_model_override() is None


def _roots(tmp_path: Path) -> tuple[Path, Path, Path]:
    project, user, builtin = (tmp_path / "project", tmp_path / "user", tmp_path / "builtin")
    for path in (project, user, builtin):
        path.mkdir()
    return project, user, builtin


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
    *,
    name: str = "skill",
    description: str = "A valid description.",
    tools: str = "[read_file]",
    mode: str = "shared",
    sop: str = "SOP",
    extra: str = "",
) -> None:
    path.write_text(
        "\n".join(
            (
                "---",
                f"name: {name}",
                f"description: {description}",
                f"tools: {tools}",
                f"mode: {mode}",
                extra,
                "---",
                sop,
            )
        ),
        encoding="utf-8",
    )


def asyncio_run(awaitable):
    import asyncio

    return asyncio.run(awaitable)
