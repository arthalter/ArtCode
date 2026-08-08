from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

import yaml


@dataclass(frozen=True)
class DangerousCommandHit:
    rule_id: str
    reason: str


@dataclass(frozen=True)
class _Rule:
    rule_id: str
    pattern: re.Pattern[str]
    reason: str


class DangerousCommandValidator:
    def __init__(self, rules: tuple[_Rule, ...]) -> None:
        self.rules = rules

    @classmethod
    def load(cls, path: Path | None = None) -> DangerousCommandValidator:
        target = path or Path(str(files("artcode.security").joinpath("dangerous_commands.yml")))
        try:
            raw = yaml.safe_load(target.read_text(encoding="utf-8"))
            items = raw["rules"]
            rules = tuple(
                _Rule(
                    rule_id=str(item["id"]),
                    pattern=re.compile(str(item["regex"])),
                    reason=str(item["reason"]),
                )
                for item in items
            )
        except (OSError, KeyError, TypeError, yaml.YAMLError, re.error) as exc:
            raise ValueError(f"危险命令规则无效：{target}（{exc}）") from exc
        if not rules or any(not rule.rule_id or not rule.reason for rule in rules):
            raise ValueError(f"危险命令规则无效：{target}")
        return cls(rules)

    def check(self, command: str, workspace: Path) -> DangerousCommandHit | None:
        normalized = command.strip()
        for rule in self.rules:
            if rule.pattern.search(normalized):
                return DangerousCommandHit(rule.rule_id, rule.reason)
        if self._deletes_workspace(normalized, workspace.resolve()):
            return DangerousCommandHit("workspace-root-delete", "禁止整体删除当前 Workspace")
        return None

    @staticmethod
    def _deletes_workspace(command: str, workspace: Path) -> bool:
        try:
            tokens = shlex.split(command)
        except ValueError:
            return False
        if not tokens or Path(tokens[0]).name != "rm":
            return False
        options = [token for token in tokens[1:] if token.startswith("-")]
        recursive = any("r" in option.lower() for option in options)
        force = any("f" in option.lower() for option in options)
        if not recursive or not force:
            return False
        for token in tokens[1:]:
            if token.startswith("-"):
                continue
            try:
                if Path(token).expanduser().resolve() == workspace:
                    return True
            except OSError:
                continue
        return False
