from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from artcode.workspace import ArtCodePaths, Workspace

from .glob import glob_match
from .models import PermissionAction, RuleSource

TOOL_NAMES = frozenset(
    {"read_file", "write_file", "edit_file", "find_files", "search_text", "run_command"}
)


class PermissionRuleError(ValueError):
    def __init__(self, path: Path, reason: str) -> None:
        self.path = path
        self.reason = reason
        super().__init__(f"权限规则文件错误：{path}（{reason}）")


@dataclass(frozen=True)
class PermissionRule:
    match: str
    action: PermissionAction
    tool_name: str
    pattern: str

    @classmethod
    def parse(cls, match: str, action: str) -> PermissionRule:
        if not isinstance(match, str):
            raise ValueError("match 必须是字符串")
        left = match.find("(")
        right = match.rfind(")")
        if left <= 0 or right != len(match) - 1 or right <= left + 1:
            raise ValueError("match 必须使用 工具名(pattern) 格式")
        tool_name = match[:left]
        pattern = match[left + 1 : right]
        if tool_name not in TOOL_NAMES:
            raise ValueError(f"未知工具名称：{tool_name}")
        try:
            parsed_action = PermissionAction(action)
        except (ValueError, TypeError) as exc:
            raise ValueError("action 只能是 allow、ask 或 deny") from exc
        if parsed_action is PermissionAction.NO_MATCH:
            raise ValueError("action 不能是 no_match")
        return cls(match=match, action=parsed_action, tool_name=tool_name, pattern=pattern)

    def matches(self, tool_name: str, target: str) -> bool:
        if self.tool_name != tool_name:
            return False
        value = target.strip() if tool_name == "run_command" else target
        return glob_match(self.pattern, value, path_mode=tool_name != "run_command")


@dataclass(frozen=True)
class RuleMatch:
    action: PermissionAction
    source: RuleSource
    path: Path
    index: int
    rule: PermissionRule


@dataclass(frozen=True)
class RulePaths:
    user: Path
    project: Path
    local: Path

    @classmethod
    def from_context(cls, paths: ArtCodePaths, workspace: Workspace) -> RulePaths:
        return cls(
            user=paths.user_permissions_file,
            project=workspace.project_permissions_file,
            local=workspace.local_permissions_file,
        )


class RuleLoader:
    def __init__(self, paths: RulePaths) -> None:
        self.paths = paths

    def validate_all(self) -> None:
        for path in (self.paths.user, self.paths.project, self.paths.local):
            self.load_file(path)

    def load_file(self, path: Path) -> list[PermissionRule]:
        if not path.exists():
            return []
        try:
            text = path.read_text(encoding="utf-8")
            raw = yaml.safe_load(text)
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            raise PermissionRuleError(path, str(exc)) from exc
        if raw is None:
            return []
        if not isinstance(raw, dict):
            raise PermissionRuleError(path, "YAML 顶层必须是对象/map")
        raw_rules = raw.get("rules", [])
        if not isinstance(raw_rules, list):
            raise PermissionRuleError(path, "rules 必须是列表")
        rules: list[PermissionRule] = []
        for index, item in enumerate(raw_rules, start=1):
            if not isinstance(item, dict) or set(item) != {"match", "action"}:
                raise PermissionRuleError(path, f"第 {index} 条规则必须且只能包含 match、action")
            try:
                rules.append(PermissionRule.parse(item["match"], item["action"]))
            except (ValueError, TypeError) as exc:
                raise PermissionRuleError(path, f"第 {index} 条规则：{exc}") from exc
        return rules

    def query(self, tool_name: str, target: str) -> RuleMatch | None:
        layers = (
            (RuleSource.USER, self.paths.user),
            (RuleSource.PROJECT, self.paths.project),
            (RuleSource.LOCAL, self.paths.local),
        )
        effective: dict[RuleSource, RuleMatch] = {}
        for source, path in layers:
            rules = self.load_file(path)
            for index, rule in enumerate(rules, start=1):
                if rule.matches(tool_name, target):
                    effective[source] = RuleMatch(rule.action, source, path, index, rule)
        for source in (RuleSource.USER, RuleSource.PROJECT, RuleSource.LOCAL):
            match = effective.get(source)
            if match and match.action is PermissionAction.DENY:
                return match
        for source in (RuleSource.LOCAL, RuleSource.PROJECT, RuleSource.USER):
            if source in effective:
                return effective[source]
        return None


def rules_document(rules: list[PermissionRule]) -> dict[str, Any]:
    return {"rules": [{"match": rule.match, "action": rule.action.value} for rule in rules]}
