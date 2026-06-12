from __future__ import annotations

from artcode.prompting.builder import PromptBuilder
from artcode.prompting.sections import PromptSection, default_fixed_sections


def test_builder_output_is_stable_for_same_input() -> None:
    builder = PromptBuilder()

    first = builder.build(default_fixed_sections())
    second = builder.build(default_fixed_sections())

    assert first == second


def test_builder_renders_sections_with_consistent_spacing() -> None:
    prompt = PromptBuilder().build(
        (
            PromptSection("b", "B", 200, "body b"),
            PromptSection("a", "A", 100, "body a"),
        )
    )

    assert prompt == "# A\n\nbody a\n\n# B\n\nbody b\n"


def test_optional_sections_are_after_fixed_sections() -> None:
    prompt = PromptBuilder().build(
        default_fixed_sections(),
        (PromptSection("custom", "自定义指令", 800, "新增功能必须补测试。"),),
    )

    assert prompt.rfind("# 文本输出") < prompt.rfind("# 自定义指令")


def test_empty_optional_sections_are_skipped() -> None:
    prompt = PromptBuilder().build(
        default_fixed_sections(),
        (
            PromptSection("empty", "长期记忆", 1000, "   "),
            PromptSection("custom", "自定义指令", 800, "保留这个模块。"),
        ),
    )

    assert "# 自定义指令" in prompt
    assert "# 长期记忆" not in prompt


def test_same_priority_sections_are_sorted_by_id() -> None:
    prompt = PromptBuilder().build(
        (),
        (
            PromptSection("zeta", "Z", 800, "z"),
            PromptSection("alpha", "A", 800, "a"),
        ),
    )

    assert prompt.index("# A") < prompt.index("# Z")
