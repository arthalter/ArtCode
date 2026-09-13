from __future__ import annotations

from pathlib import Path

from artcode._skill import LocalSkills
from tests.contracts.test_skill_interface import write_skill


def test_invalid_high_priority_candidate_blocks_lower_fallback_but_not_other_skill(tmp_path: Path) -> None:
    project = tmp_path / "project"
    user = tmp_path / "user"
    write_skill(user, "review", sop="user-valid")
    write_skill(project, "review", sop="project-will-break").write_text("not frontmatter", encoding="utf-8")
    write_skill(user, "other", sop="other-valid")
    skills = LocalSkills(project, user, tmp_path / "builtin", known_tools=lambda: {"read_file"})

    catalog = skills.refresh()

    assert all(item.name != "review" for item in catalog.skills)
    assert any(item.name == "other" for item in catalog.skills)
    assert skills.activate("review").ok is False
    assert skills.activate("other").ok is True


def test_invalid_hot_update_preserves_active_last_valid_snapshot_then_recovers(tmp_path: Path) -> None:
    project = tmp_path / "project"
    path = write_skill(project, "review", sop="VALID-V1")
    skills = LocalSkills(project, tmp_path / "user", tmp_path / "builtin", known_tools=lambda: {"read_file"})
    skills.refresh()
    assert skills.activate("review").ok
    assert "VALID-V1" in skills.freeze().contributions[0].instructions

    path.write_text("broken", encoding="utf-8")
    broken = skills.freeze()
    assert "VALID-V1" in broken.contributions[0].instructions
    assert any("最后有效" in item.message for item in skills.snapshot().diagnostics)

    write_skill(project, "review", sop="VALID-V2")
    assert "VALID-V2" in skills.freeze().contributions[0].instructions
