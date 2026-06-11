from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PlanMemory:
    latest_plan: str | None = None

    def save(self, plan: str) -> None:
        stripped = plan.strip()
        if stripped:
            self.latest_plan = stripped

    def get(self) -> str | None:
        return self.latest_plan

    def clear(self) -> None:
        self.latest_plan = None
