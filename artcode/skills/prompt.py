from __future__ import annotations

from .models import SkillRunSnapshot


def skill_prompt_messages(snapshot: SkillRunSnapshot) -> tuple[dict[str, str], ...]:
    """Return request-only system messages; SOP never enters Conversation history."""
    messages: list[dict[str, str]] = []
    if snapshot.catalog.definitions:
        lines = [
            "<available-skills>",
            "以下是可按需加载的本地 Skill；需要时调用 load_skill，未加载前不要假设其 SOP 内容。",
            "当用户明确要求使用某个列出的 Skill 时，必须先调用 load_skill 加载该名称；不能只在文本中声称已经加载。",
        ]
        lines.extend(
            f"- {item.name}: {item.metadata.description}"
            for item in snapshot.catalog.definitions
        )
        lines.append("</available-skills>")
        messages.append({"role": "system", "content": "\n".join(lines)})
    if snapshot.active:
        lines = ["<active-skills>"]
        for active in snapshot.active:
            definition = active.definition
            lines.extend(
                (
                    f'<skill name="{definition.name}" mode="{definition.metadata.mode.value}">',
                    definition.sop,
                    "</skill>",
                )
            )
        lines.append("</active-skills>")
        messages.append({"role": "system", "content": "\n".join(lines)})
    return tuple(messages)
