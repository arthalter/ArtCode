from __future__ import annotations

from copy import deepcopy

from artcode.prompts import SYSTEM_PROMPT


Message = dict[str, str]


class ConversationContext:
    def __init__(self, system_prompt: str = SYSTEM_PROMPT) -> None:
        self._messages: list[Message] = [{"role": "system", "content": system_prompt}]

    def append_user(self, content: str) -> None:
        self._append("user", content)

    def append_assistant(self, content: str) -> None:
        self._append("assistant", content)

    def export_messages(self) -> list[Message]:
        return deepcopy(self._messages)

    def _append(self, role: str, content: str) -> None:
        self._messages.append({"role": role, "content": content})
