from __future__ import annotations

from artcode.prompting import build_system_prompt, default_fixed_sections


def test_default_fixed_sections_are_the_seven_fixed_modules() -> None:
    sections = default_fixed_sections()

    assert [section.title for section in sections] == [
        "身份",
        "系统约束",
        "任务模式",
        "动作执行",
        "工具使用",
        "语气风格",
        "文本输出",
    ]
    assert [section.priority for section in sections] == [100, 200, 300, 400, 500, 600, 700]


def test_default_system_prompt_contains_system_reminder_rule() -> None:
    prompt = build_system_prompt()

    assert "<system-reminder>" in prompt
    assert "系统级补充约束" in prompt


def test_default_system_prompt_does_not_include_dynamic_runtime_values() -> None:
    prompt = build_system_prompt()

    forbidden = [
        "/Users/arthalter/Work/ArtCode",
        "allowed_dirs",
        "当前工作目录：",
        "当前平台：",
        "current_date",
        "timezone",
        "第 1 轮",
        "用户任务",
    ]
    for text in forbidden:
        assert text not in prompt
