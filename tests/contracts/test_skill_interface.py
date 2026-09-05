from __future__ import annotations

from pathlib import Path

from artcode._skill import LocalSkills
from artcode.core.skill import SkillMode, SkillSource


def write_skill(
    root: Path,
    name: str,
    *,
    description: str = "Useful skill",
    tools: tuple[str, ...] = ("read_file",),
    mode: str = "shared",
    history_turns: int | None = None,
    model: str | None = None,
    sop: str = "SOP-v1",
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    history = f"history_turns: {history_turns}\n" if history_turns is not None else ""
    selected_model = f"model: {model}\n" if model is not None else ""
    path = root / f"{name}.md"
    path.write_text(
        "---\n"
        f"name: {name}\n"
        f"description: {description}\n"
        f"tools: {list(tools)!r}\n"
        f"mode: {mode}\n"
        f"{history}{selected_model}"
        "---\n"
        f"{sop}\n",
        encoding="utf-8",
    )
    return path


def test_source_priority_is_whole_definition_override(tmp_path: Path) -> None:
    project = tmp_path / "project"
    user = tmp_path / "user"
    builtin = tmp_path / "builtin"
    extension = tmp_path / "extension"
    write_skill(extension, "review", description="extension", sop="extension-sop")
    write_skill(builtin, "review", description="builtin", sop="builtin-sop")
    write_skill(user, "review", description="user", sop="user-sop")
    write_skill(project, "review", description="project", tools=("read_file", "search_text"), sop="project-sop")

    skills = LocalSkills(project, user, builtin, extension_roots=(extension,), known_tools=lambda: {"read_file", "search_text"})
    catalog = skills.refresh()
    activated = skills.activate("review")
    frozen = skills.freeze()

    assert catalog.skills[0].source is SkillSource.PROJECT
    assert catalog.skills[0].description == "project"
    assert activated.ok is True
    assert frozen.contributions[0].instructions.strip() == "project-sop"
    assert frozen.allowed_tools == frozenset({"read_file", "search_text"})


def test_discovery_is_two_stage_and_activation_loads_latest_sop(tmp_path: Path) -> None:
    path = write_skill(tmp_path / "project", "review", sop="OLD-SOP")
    skills = LocalSkills(tmp_path / "project", tmp_path / "user", tmp_path / "builtin", known_tools=lambda: {"read_file"})

    catalog = skills.refresh()
    assert "OLD-SOP" not in repr(catalog)
    path.write_text(path.read_text(encoding="utf-8").replace("OLD-SOP", "NEW-SOP"), encoding="utf-8")
    skills.activate("review")

    assert skills.freeze().contributions[0].instructions.strip() == "NEW-SOP"


def test_explicit_and_natural_language_selection_share_activation_owner(tmp_path: Path) -> None:
    write_skill(tmp_path / "project", "review", description="Review Python changes")
    skills = LocalSkills(tmp_path / "project", tmp_path / "user", tmp_path / "builtin", known_tools=lambda: {"read_file"})
    skills.refresh()

    first = skills.select("Please use review for this change")
    second = skills.activate("review")

    assert first.ok is True
    assert second.already_active is True
    assert skills.snapshot().active == ("review",)
    skills.clear()
    assert skills.snapshot().active == ()


def test_model_unavailable_fails_without_fallback(tmp_path: Path) -> None:
    write_skill(tmp_path / "project", "review", model="special-model")
    skills = LocalSkills(
        tmp_path / "project",
        tmp_path / "user",
        tmp_path / "builtin",
        known_tools=lambda: {"read_file"},
        available_models=lambda: {"default-model"},
    )
    skills.refresh()

    result = skills.activate("review")

    assert result.ok is False
    assert "不可用" in result.message
    assert skills.snapshot().active == ()


def test_isolated_metadata_requires_history_and_shared_rejects_it(tmp_path: Path) -> None:
    write_skill(tmp_path / "project", "isolated", mode="isolated", history_turns=2)
    write_skill(tmp_path / "project", "badshared", mode="shared", history_turns=1)
    skills = LocalSkills(tmp_path / "project", tmp_path / "user", tmp_path / "builtin", known_tools=lambda: {"read_file"})

    catalog = skills.refresh()

    assert next(item for item in catalog.skills if item.name == "isolated").mode is SkillMode.ISOLATED
    assert all(item.name != "badshared" for item in catalog.skills)
    assert any("shared" in item.message for item in catalog.diagnostics)
