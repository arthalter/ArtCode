from __future__ import annotations

from hypothesis import given, strategies as st
import pytest

from artcode.agent import PLAN_MODE
from artcode.tools import (
    DescriptorBackedTool,
    ToolDescriptor,
    ToolEffect,
    ToolOrigin,
    ToolRegistry,
)

pytestmark = [pytest.mark.ch10_5, pytest.mark.property]


names = st.text(alphabet=st.characters(categories=("Ll", "Lu")), min_size=1, max_size=12)
builtin_effects = st.sampled_from(list(ToolEffect))


class MetadataTool(DescriptorBackedTool):
    def __init__(self, descriptor: ToolDescriptor) -> None:
        self.descriptor = descriptor


def descriptor(
    name: str,
    effect: ToolEffect,
    origin: ToolOrigin = ToolOrigin.BUILTIN,
) -> ToolDescriptor:
    return ToolDescriptor(
        name,
        "description",
        {"type": "object", "properties": {"value": {"type": "string"}}},
        effect,
        origin,
        origin is ToolOrigin.BUILTIN,
    )


@given(names, builtin_effects, st.booleans())
def test_builtin_descriptor_roundtrips_through_registry_export(
    name: str,
    effect: ToolEffect,
    rule_configurable: bool,
) -> None:
    item = ToolDescriptor(
        name,
        "description",
        {"type": "object"},
        effect,
        ToolOrigin.BUILTIN,
        rule_configurable,
    )
    registry = ToolRegistry()
    registry.register(MetadataTool(item))
    exported = registry.openai_tools(include_internal_metadata=True)[0]
    assert exported["function"]["name"] == name
    assert exported["x-artcode-effect"] == effect.value
    assert exported["x-artcode-rule-configurable"] is rule_configurable


@given(names)
def test_every_mcp_descriptor_is_external_visible_and_never_rule_configurable(name: str) -> None:
    item = descriptor(name, ToolEffect.EXTERNAL, ToolOrigin.MCP)
    registry = ToolRegistry()
    registry.register(MetadataTool(item))
    exported = registry.openai_tools(include_internal_metadata=True)
    assert PLAN_MODE.tool_policy.filter_openai_tools(exported) == exported
    assert not item.rule_configurable


@given(names, builtin_effects)
def test_plan_visibility_is_derived_only_from_builtin_effect(name: str, effect: ToolEffect) -> None:
    registry = ToolRegistry()
    registry.register(MetadataTool(descriptor(name, effect)))
    exported = registry.openai_tools(include_internal_metadata=True)
    selected = PLAN_MODE.tool_policy.filter_openai_tools(exported)
    assert bool(selected) is (effect is ToolEffect.READ)


@given(st.lists(names, min_size=1, max_size=12, unique=True))
def test_registry_preserves_descriptor_registration_order(values: list[str]) -> None:
    registry = ToolRegistry()
    for value in values:
        registry.register(MetadataTool(descriptor(value, ToolEffect.READ)))
    assert [item.name for item in registry.descriptors()] == values
    assert [item["function"]["name"] for item in registry.openai_tools()] == values


@given(names, builtin_effects)
def test_registry_rejects_any_duplicate_descriptor_name(name: str, effect: ToolEffect) -> None:
    registry = ToolRegistry()
    registry.register(MetadataTool(descriptor(name, effect)))
    with pytest.raises(ValueError, match="already registered"):
        registry.register(MetadataTool(descriptor(name, ToolEffect.READ)))
