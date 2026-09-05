from __future__ import annotations

from artcode.core.model import ModelRequest
from artcode.core.session import PromptBudget


def estimate_request(request: ModelRequest) -> PromptBudget:
    characters = sum(len(message.content or "") for message in request.prompt)
    characters += sum(len(tool.description) + len(tool.parameters_json) for tool in request.tools)
    return PromptBudget(max(1, (characters + 3) // 4), "deterministic_estimate")
