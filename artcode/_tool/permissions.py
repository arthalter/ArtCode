from __future__ import annotations

import os
from pathlib import Path
import tempfile

import yaml

from artcode.core.tool import (
    PermissionMode,
    PermissionRule,
    PermissionSnapshot,
    ShellPolicy,
)


class PermissionStore:
    def __init__(
        self,
        *,
        mode: PermissionMode,
        shell_policy: ShellPolicy,
        path: Path | None,
    ) -> None:
        self.mode = mode
        self.shell_policy = shell_policy
        self.path = path
        self.rules = list(self._load())

    def snapshot(self) -> PermissionSnapshot:
        return PermissionSnapshot(self.mode, self.shell_policy, tuple(self.rules))

    def set_mode(self, mode: PermissionMode) -> PermissionSnapshot:
        if not isinstance(mode, PermissionMode):
            raise TypeError("mode must be PermissionMode")
        self.mode = mode
        return self.snapshot()

    def set_shell(self, policy: ShellPolicy) -> PermissionSnapshot:
        if not isinstance(policy, ShellPolicy):
            raise TypeError("policy must be ShellPolicy")
        self.shell_policy = policy
        return self.snapshot()

    def add_exact(self, tool_name: str, target: str, *, allow: bool) -> None:
        self.rules = [
            rule for rule in self.rules
            if not (rule.tool_name == tool_name and rule.target == target)
        ]
        self.rules.append(PermissionRule(tool_name, target, allow))
        self._save()

    def _load(self) -> tuple[PermissionRule, ...]:
        if self.path is None or not self.path.exists():
            return ()
        if self.path.is_symlink():
            raise ValueError("权限规则文件不能是符号链接。")
        try:
            raw = yaml.safe_load(self.path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise ValueError(f"权限规则无法读取：{exc}") from exc
        if raw is None:
            return ()
        if not isinstance(raw, dict) or set(raw) != {"version", "rules"} or raw["version"] != 1:
            raise ValueError("权限规则必须是 version: 1 和 rules 列表。")
        if not isinstance(raw["rules"], list):
            raise ValueError("权限 rules 必须是列表。")
        rules: list[PermissionRule] = []
        for item in raw["rules"]:
            if not isinstance(item, dict) or set(item) != {"tool", "target", "allow"}:
                raise ValueError("每条权限规则必须包含 tool、target、allow。")
            if not isinstance(item["tool"], str) or not isinstance(item["target"], str) or not isinstance(item["allow"], bool):
                raise ValueError("权限规则字段类型无效。")
            rules.append(PermissionRule(item["tool"], item["target"], item["allow"]))
        return tuple(rules)

    def _save(self) -> None:
        if self.path is None:
            return
        if self.path.is_symlink() or self.path.parent.is_symlink():
            raise ValueError("权限规则路径不能是符号链接。")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "rules": [
                {"tool": rule.tool_name, "target": rule.target, "allow": rule.allow}
                for rule in self.rules
            ],
        }
        temporary: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=self.path.parent, prefix=".permissions-", delete=False
            ) as handle:
                temporary = handle.name
                os.chmod(temporary, 0o600)
                yaml.safe_dump(payload, handle, allow_unicode=True, sort_keys=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            temporary = None
            os.chmod(self.path, 0o600)
        finally:
            if temporary is not None:
                Path(temporary).unlink(missing_ok=True)
