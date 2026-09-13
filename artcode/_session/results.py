from __future__ import annotations

from artcode.core.model import ModelRequest
from artcode.core.session import PromptBudget


def estimate_request(request: ModelRequest) -> PromptBudget:
    # Include all transmitted material, including opaque continuation fields.
    # UTF-8 bytes make non-ASCII prompts less severely underestimated than chars.
    def size(text: str) -> int:
        return len(text.encode("utf-8"))

    characters = 0
    for message in request.prompt:
        characters += 16 + size(message.role) + size(message.content or "")
        characters += size(message.tool_request_id or "")
        if message.metadata is not None:
            characters += len(message.metadata.envelope)
        characters += sum(
            16 + size(call.id) + size(call.name) + size(call.arguments_json)
            for call in message.tool_requests
        )
    characters += sum(
        16 + size(tool.name) + size(tool.description) + size(tool.parameters_json)
        for tool in request.tools
    )
    return PromptBudget(max(1, (characters + 3) // 4), "deterministic_estimate")
