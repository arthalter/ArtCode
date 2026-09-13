from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from hypothesis import given, strategies as st

from artcode._skill import LocalSkills


TOOLS = ("read_file", "find_files", "search_text", "write_file", "edit_file", "run_command")


@given(st.lists(st.sets(st.sampled_from(TOOLS)), min_size=1, max_size=5))
def test_multiple_active_skill_capabilities_are_exact_intersection(scopes: list[set[str]]) -> None:
    with TemporaryDirectory() as raw:
        root = Path(raw)
        project = root / "skills"
        project.mkdir()
        for index, scope in enumerate(scopes):
            (project / f"skill{index}.md").write_text(
                "---\n"
                f"name: skill{index}\n"
                f"description: skill {index}\n"
                f"tools: {sorted(scope)!r}\n"
                "mode: shared\n"
                "---\nSOP\n",
                encoding="utf-8",
            )
        skills = LocalSkills(project, root / "user", root / "builtin", known_tools=lambda: set(TOOLS))
        skills.refresh()
        for index in range(len(scopes)):
            assert skills.activate(f"skill{index}").ok

        assert skills.freeze().allowed_tools == frozenset.intersection(*(frozenset(item) for item in scopes))
