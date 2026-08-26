from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

import yaml

from artcode.permissions import PermissionMode
from artcode.tools import ToolDescriptor, ToolEffect, ToolOrigin

from .models import IsolationMode, RoleDefinition, RoleSource


_ROLE_NAME = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
_FRONTMATTER = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.DOTALL)
_ROLE_FIELDS = frozenset(
    {"name", "description", "tools", "model", "max_rounds", "permission_mode", "isolation"}
)
_TOOLS_FIELDS = frozenset({"allow", "deny"})


@dataclass(frozen=True)
class RoleDiagnostic:
    path: Path
    code: str
    message: str
    role_name: str | None = None
    blocking: bool = False

    def render(self) -> str:
        prefix = f"[{self.role_name}] " if self.role_name else ""
        return f"{prefix}{self.path}: {self.message}"


@dataclass(frozen=True)
class RoleSnapshot:
    definitions: Mapping[str, RoleDefinition]
    diagnostics: tuple[RoleDiagnostic, ...]

    def get(self, name: str) -> RoleDefinition | None:
        return self.definitions.get(name)


class RoleCatalog:
    """Refreshable role catalog with all-or-nothing source precedence.

    A malformed project role is deliberately remembered as a blocker. Falling
    back to a lower-priority role with the same name would be surprising and
    can silently widen a role's capabilities.
    """

    def __init__(
        self,
        *,
        project_dir: Path,
        user_dir: Path,
        builtin_dir: Path,
        plugin_dirs: Iterable[Path] = (),
        model_tiers: Mapping[str, str] | None = None,
    ) -> None:
        self.project_dir = project_dir
        self.user_dir = user_dir
        self.builtin_dir = builtin_dir
        self.plugin_dirs = tuple(plugin_dirs)
        self.model_tiers = dict(model_tiers or {})
        self._snapshot = RoleSnapshot({}, ())

    @property
    def snapshot(self) -> RoleSnapshot:
        return self._snapshot

    def refresh(self, descriptors: Iterable[ToolDescriptor]) -> RoleSnapshot:
        descriptor_map = {item.name: item for item in descriptors}
        sources: list[tuple[RoleSource, tuple[Path, ...]]] = [
            (RoleSource.PROJECT, (self.project_dir,)),
            (RoleSource.USER, (self.user_dir,)),
            (RoleSource.BUILTIN, (self.builtin_dir,)),
            (RoleSource.PLUGIN, self.plugin_dirs),
        ]
        selected: dict[str, RoleDefinition] = {}
        diagnostics: list[RoleDiagnostic] = []
        claimed: set[str] = set()
        for source, directories in sources:
            by_name: dict[str, list[tuple[Path, RoleDefinition | None, RoleDiagnostic | None]]] = {}
            for directory in directories:
                for path in _role_files(directory):
                    parsed, issue, claimed_name = _parse_role(
                        path, source, descriptor_map, self.model_tiers
                    )
                    name = parsed.name if parsed is not None else claimed_name
                    if name is None:
                        diagnostics.append(issue or RoleDiagnostic(path, "invalid_role", "角色定义无效。"))
                        continue
                    by_name.setdefault(name, []).append((path, parsed, issue))
            for name in sorted(by_name):
                if name in claimed:
                    continue
                claimed.add(name)
                items = by_name[name]
                if len(items) > 1:
                    paths = "、".join(str(item[0]) for item in items)
                    diagnostics.append(
                        RoleDiagnostic(
                            items[0][0],
                            "duplicate_role",
                            f"同一来源存在多个同名角色：{paths}",
                            name,
                            True,
                        )
                    )
                    continue
                _, parsed, issue = items[0]
                if parsed is not None:
                    selected[name] = parsed
                else:
                    diagnostics.append(
                        issue or RoleDiagnostic(items[0][0], "invalid_role", "角色定义无效。", name, True)
                    )
        self._snapshot = RoleSnapshot(dict(selected), tuple(diagnostics))
        return self._snapshot


def _role_files(directory: Path) -> tuple[Path, ...]:
    try:
        if not directory.exists() or directory.is_symlink() or not directory.is_dir():
            return ()
        return tuple(sorted(path for path in directory.glob("*.md") if path.is_file() and not path.is_symlink()))
    except OSError:
        return ()


def _parse_role(
    path: Path,
    source: RoleSource,
    descriptors: Mapping[str, ToolDescriptor],
    model_tiers: Mapping[str, str],
) -> tuple[RoleDefinition | None, RoleDiagnostic | None, str | None]:
    claimed_name: str | None = path.stem if _ROLE_NAME.fullmatch(path.stem) else None
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return None, RoleDiagnostic(path, "unreadable", f"无法读取角色：{exc}"), None
    match = _FRONTMATTER.match(text)
    if match is None:
        return None, RoleDiagnostic(path, "frontmatter", "角色必须以 YAML frontmatter 开头。"), None
    try:
        raw = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        return None, RoleDiagnostic(path, "frontmatter", f"角色 YAML 无效：{exc}"), None
    if not isinstance(raw, dict):
        return None, RoleDiagnostic(path, "frontmatter", "角色 frontmatter 必须是对象。"), None
    try:
        _unknown(raw, _ROLE_FIELDS, "角色 frontmatter")
        missing = sorted(_ROLE_FIELDS - set(raw))
        if missing:
            raise ValueError(f"角色 frontmatter 缺少字段：{'、'.join(missing)}。")
        name = _required_name(raw)
        if name != path.stem:
            raise ValueError("角色 name 必须与 Markdown 文件名完全一致。")
        description = _required_description(raw)
        body = text[match.end():]
        if not body.strip():
            raise ValueError("角色正文不能为空。")
        allowed, denied = _parse_tools(raw["tools"], descriptors)
        model = raw["model"]
        if not isinstance(model, str) or model not in {"inherit", "haiku", "sonnet", "opus"}:
            raise ValueError("model 只能是 inherit、haiku、sonnet 或 opus。")
        if model != "inherit" and model not in model_tiers:
            raise ValueError(f"模型档位未配置：{model}。")
        max_rounds = raw["max_rounds"]
        if isinstance(max_rounds, bool) or not isinstance(max_rounds, int) or not 1 <= max_rounds <= 100:
            raise ValueError("max_rounds 必须是 1～100 的整数。")
        permission_raw = raw["permission_mode"]
        try:
            permission_mode = PermissionMode(permission_raw)
        except (TypeError, ValueError):
            raise ValueError("permission_mode 只能是 default、edit 或 full。") from None
        try:
            isolation = IsolationMode(raw["isolation"])
        except (TypeError, ValueError):
            raise ValueError("isolation 只能是 none 或 worktree。") from None
        writes = _includes_write(allowed, descriptors)
        if writes and isolation is not IsolationMode.WORKTREE:
            raise ValueError("允许 write 或 shell 工具的角色必须声明 isolation: worktree。")
        return RoleDefinition(
            name=name,
            description=description,
            system_prompt=body,
            source=source,
            path=path,
            tool_allow=allowed,
            tool_deny=denied,
            model_tier=model,
            max_rounds=max_rounds,
            permission_mode=permission_mode,
            isolation=isolation,
        ), None, name
    except ValueError as exc:
        return None, RoleDiagnostic(path, "invalid_role", str(exc), claimed_name, bool(claimed_name)), claimed_name


def _unknown(raw: Mapping[str, object], allowed: frozenset[str], label: str) -> None:
    unknown = sorted(str(key) for key in raw if key not in allowed)
    if unknown:
        raise ValueError(f"{label}包含未知字段：{'、'.join(unknown)}。")


def _required_name(raw: Mapping[str, object]) -> str:
    name = raw.get("name")
    if not isinstance(name, str):
        raise ValueError("name 必须是字符串。")
    if not _ROLE_NAME.fullmatch(name):
        raise ValueError("角色 name 必须匹配 ^[a-z][a-z0-9-]{0,31}$。")
    return name


def _required_description(raw: Mapping[str, object]) -> str:
    value = raw.get("description")
    if not isinstance(value, str) or not 1 <= len(value) <= 200 or "\n" in value or "\r" in value:
        raise ValueError("description 必须是 1～200 个 Unicode 字符的单行文本。")
    if not value.strip():
        raise ValueError("description 不能为空白文本。")
    return value


def _required_string(raw: Mapping[str, object], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} 必须是非空字符串。")
    return value.strip()


def _parse_tools(
    raw: object,
    descriptors: Mapping[str, ToolDescriptor],
) -> tuple[frozenset[str], frozenset[str]]:
    if not isinstance(raw, dict):
        raise ValueError("tools 必须是对象，包含可选 allow 与 deny 列表。")
    _unknown(raw, _TOOLS_FIELDS, "tools")
    if set(raw) != _TOOLS_FIELDS:
        missing = sorted(_TOOLS_FIELDS - set(raw))
        raise ValueError(f"tools 必须同时包含 allow 与 deny；缺少：{'、'.join(missing) or '无'}。")
    allow = _name_set(raw["allow"], "tools.allow")
    deny = _name_set(raw["deny"], "tools.deny")
    names = {
        name
        for name, descriptor in descriptors.items()
        if descriptor.subagent_allowed and descriptor.origin is ToolOrigin.BUILTIN
    }
    unknown = sorted((set(allow) | set(deny)) - names)
    if unknown:
        raise ValueError(f"角色引用未知工具：{'、'.join(unknown)}。")
    if allow is not None and allow & deny:
        raise ValueError("tools.allow 与 tools.deny 不能包含同一工具。")
    return allow, deny


def _name_set(raw: object, label: str) -> frozenset[str]:
    if not isinstance(raw, list) or any(not isinstance(item, str) or not item.strip() for item in raw):
        raise ValueError(f"{label} 必须是非空字符串列表。")
    values = frozenset(item.strip() for item in raw)
    if len(values) != len(raw):
        raise ValueError(f"{label} 不能包含重复项。")
    return values


def _includes_write(
    allow: frozenset[str],
    descriptors: Mapping[str, ToolDescriptor],
) -> bool:
    return any(
        descriptors[name].effect in {ToolEffect.WRITE, ToolEffect.SHELL}
        for name in allow
    )
