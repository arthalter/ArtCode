from __future__ import annotations

from typing import Any

from artcode.tools.base import (
    DescriptorBackedTool,
    PreparedToolCall,
    ToolDescriptor,
    ToolEffect,
    ToolOrigin,
    ToolPreview,
    ToolRunContext,
)
from artcode.tools.results import ToolResult, error_result, success_result

from .service import SkillService


class LoadSkillTool(DescriptorBackedTool):
    descriptor = ToolDescriptor(
        name="load_skill",
        description="按名称加载一个已发现的本地 Skill，使其 SOP 与工具白名单从下一轮开始生效。",
        parameters_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Skill 目录中显示的名称。"}
            },
            "required": ["name"],
            "additionalProperties": False,
        },
        effect=ToolEffect.READ,
        origin=ToolOrigin.SYSTEM,
        rule_configurable=False,
    )

    def __init__(self, service: SkillService) -> None:
        self.service = service

    def prepare(
        self,
        arguments: dict[str, Any],
        context: ToolRunContext,
    ) -> PreparedToolCall | ToolResult:
        if set(arguments) != {"name"}:
            return error_result(self.name, "invalid_arguments", "load_skill 只接受 name 参数。")
        name = arguments.get("name")
        if (
            not isinstance(name, str)
            or not name.strip()
            or name.strip() in {".", ".."}
            or "/" in name
            or "\\" in name
        ):
            return error_result(self.name, "invalid_arguments", "name 必须是目录中的 Skill 名称，不能是路径。")
        return PreparedToolCall(
            tool=self,
            arguments={"name": name.strip().lower()},
            preview=ToolPreview(self.name, f"加载 Skill {name.strip().lower()}", name.strip().lower()),
        )

    async def execute(self, prepared: PreparedToolCall, context: ToolRunContext) -> ToolResult:
        outcome = self.service.activate(
            prepared.arguments["name"],
            for_model_execution=True,
        )
        if not outcome.ok:
            return error_result(self.name, "skill_not_found", outcome.message)
        definition = outcome.definition
        assert definition is not None
        resources = ()
        if definition.package_root.is_dir():
            resources = tuple(
                path.relative_to(definition.package_root).as_posix()
                for path in definition.resources
                if path != definition.entry_path
            )
        resource_block = "\n".join(f"- {item}" for item in resources) or "- （无附属资源）"
        return success_result(
            self.name,
            outcome.message,
            "\n".join(
                (
                    f"name: {definition.name}",
                    f"mode: {definition.metadata.mode.value}",
                    "resources:",
                    resource_block,
                )
            ),
        )
