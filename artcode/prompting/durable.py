from __future__ import annotations

from pathlib import Path

from artcode.persistence.instructions import InstructionLoader
from artcode.persistence.models import InstructionBundle
from artcode.persistence.paths import DurablePaths

from .builder import PromptBuilder
from .sections import (
    default_fixed_sections,
    durable_instruction_sections,
    durable_memory_section,
)


class DurablePromptSource:
    """Build the stable prompt from instructions and the latest memory indexes.

    This source is intentionally read-only: it owns no session, reminder flag,
    note store, updater, or background task.
    """

    def __init__(
        self,
        paths: DurablePaths,
        *,
        instructions: InstructionBundle | None = None,
    ) -> None:
        self.paths = paths
        self.instructions = instructions or InstructionLoader(paths).load()

    def build_system_prompt(self) -> str:
        optional = [*durable_instruction_sections(self.instructions)]
        optional.append(
            durable_memory_section(
                _read_index(self.paths.user_memory_dir / "index.md"),
                _read_index(self.paths.project_memory_dir / "index.md"),
            )
        )
        return PromptBuilder().build(default_fixed_sections(), optional)


def _read_index(path: Path) -> str:
    try:
        if path.is_symlink() or not path.is_file():
            return ""
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""
