from __future__ import annotations

import re
import shlex
from pathlib import Path

import yaml

from artcode.core.tool import (
    PermissionMode,
    PermissionRule,
    RunMode,
    ShellPolicy,
    ToolDescriptor,
    ToolEffect,
    ToolRun,
)


class DangerousCommands:
    def __init__(self, path: Path) -> None:
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            self._rules = tuple(
                (str(item["id"]), re.compile(str(item["regex"])), str(item["reason"]))
                for item in raw["rules"]
            )
        except (OSError, KeyError, TypeError, re.error, yaml.YAMLError) as exc:
            raise ValueError(f"危险命令规则无效：{exc}") from exc

    def check(self, command: str, workspace: Path) -> str | None:
        for identifier, pattern, reason in self._rules:
            if pattern.search(command.strip()):
                return f"{identifier}：{reason}"
        try:
            tokens = shlex.split(command)
        except ValueError:
            return None
        if tokens and Path(tokens[0]).name == "rm":
            options = [item for item in tokens[1:] if item.startswith("-")]
            recursive = any("r" in item.casefold() for item in options)
            force = any("f" in item.casefold() for item in options)
            targets = [item for item in tokens[1:] if not item.startswith("-")]
            if recursive and force:
                for target in targets:
                    try:
                        if Path(target).expanduser().resolve() == workspace.resolve():
                            return "workspace-root-delete：禁止整体删除当前 Workspace"
                    except OSError:
                        pass
        return None


def explicit_rule(run: ToolRun, descriptor: ToolDescriptor, target: str) -> PermissionRule | None:
    return next(
        (
            rule for rule in reversed(run.permission.rules)
            if rule.tool_name == descriptor.name and rule.target == target
        ),
        None,
    )


def mode_action(run: ToolRun, descriptor: ToolDescriptor) -> str:
    if descriptor.effect is ToolEffect.OBSERVE:
        return "allow"
    if descriptor.name == "run_command":
        return "allow" if run.permission.shell_policy is ShellPolicy.SANDBOX_AUTO else "ask"
    if descriptor.effect is ToolEffect.CHANGE:
        return "ask" if run.permission.mode is PermissionMode.DEFAULT else "allow"
    if descriptor.effect is ToolEffect.CONTROL:
        return "allow"
    return "ask"
