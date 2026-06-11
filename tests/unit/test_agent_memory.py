from __future__ import annotations

from artcode.agent import PlanMemory


def test_plan_memory_saves_non_empty_plan() -> None:
    memory = PlanMemory()

    memory.save("  plan  ")

    assert memory.get() == "plan"


def test_plan_memory_ignores_empty_plan_and_can_clear() -> None:
    memory = PlanMemory("old")

    memory.save("  ")
    assert memory.get() == "old"

    memory.clear()
    assert memory.get() is None
