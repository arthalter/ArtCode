from __future__ import annotations

from collections.abc import Sequence

from .sections import PromptSection, default_fixed_sections


class PromptBuilder:
    def build(
        self,
        fixed_sections: Sequence[PromptSection],
        optional_sections: Sequence[PromptSection] = (),
    ) -> str:
        sections = [
            section
            for section in (*fixed_sections, *optional_sections)
            if section.content.strip()
        ]
        ordered = sorted(sections, key=lambda section: (section.priority, section.id))
        rendered = [self._render_section(section) for section in ordered]
        return "\n\n".join(rendered).strip() + "\n"

    def _render_section(self, section: PromptSection) -> str:
        return f"# {section.title}\n\n{section.content.strip()}"


def build_system_prompt(optional_sections: Sequence[PromptSection] = ()) -> str:
    return PromptBuilder().build(default_fixed_sections(), optional_sections)
