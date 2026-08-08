from __future__ import annotations

from .base import CommandDefinition, CommandType


class CommandRegistrationError(ValueError):
    pass


class CommandRegistry:
    def __init__(self) -> None:
        self._definitions: list[CommandDefinition] = []
        self._index: dict[str, CommandDefinition] = {}

    def register(self, definition: CommandDefinition) -> None:
        identifiers = (definition.name, *definition.aliases)
        self._validate_definition(definition, identifiers)

        local: dict[str, str] = {}
        normalized_identifiers: list[str] = []
        for identifier in identifiers:
            normalized = identifier.lower()
            if normalized in local:
                raise CommandRegistrationError(
                    f"命令 {definition.name} 内部标识冲突：{identifier} 与 {local[normalized]}。"
                )
            local[normalized] = identifier
            existing = self._index.get(normalized)
            if existing is not None:
                raise CommandRegistrationError(
                    f"命令标识冲突：{identifier} 同时属于 {existing.name} 和 {definition.name}。"
                )
            normalized_identifiers.append(normalized)

        self._definitions.append(definition)
        for normalized in normalized_identifiers:
            self._index[normalized] = definition

    def resolve(self, identifier: str) -> CommandDefinition | None:
        return self._index.get(identifier.strip().lower())

    def definitions(self, *, include_hidden: bool = False) -> tuple[CommandDefinition, ...]:
        if include_hidden:
            return tuple(self._definitions)
        return tuple(definition for definition in self._definitions if not definition.hidden)

    @staticmethod
    def _validate_definition(
        definition: CommandDefinition,
        identifiers: tuple[str, ...],
    ) -> None:
        if not isinstance(definition.command_type, CommandType):
            raise CommandRegistrationError(f"命令 {definition.name!r} 的类型无效。")
        if not callable(definition.handler):
            raise CommandRegistrationError(f"命令 {definition.name!r} 缺少可调用处理行为。")
        if not definition.description.strip():
            raise CommandRegistrationError(f"命令 {definition.name!r} 缺少描述。")
        if not definition.usage or any(not item.strip() for item in definition.usage):
            raise CommandRegistrationError(f"命令 {definition.name!r} 缺少有效用法。")
        if definition.argument_hint is not None and not definition.argument_hint.strip():
            raise CommandRegistrationError(f"命令 {definition.name!r} 的参数提示不能为空。")
        for identifier in identifiers:
            if (
                not identifier
                or identifier != identifier.strip()
                or not identifier.startswith("/")
                or any(character.isspace() for character in identifier)
            ):
                raise CommandRegistrationError(f"命令标识无效：{identifier!r}。")
