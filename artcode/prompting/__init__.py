from .builder import PromptBuilder, build_system_prompt
from .sections import PromptSection, default_fixed_sections

__all__ = [
    "PromptBuilder",
    "PromptSection",
    "build_system_prompt",
    "default_fixed_sections",
    "DurablePromptSource",
]


def __getattr__(name: str):
    if name == "DurablePromptSource":
        from .durable import DurablePromptSource

        return DurablePromptSource
    raise AttributeError(name)
