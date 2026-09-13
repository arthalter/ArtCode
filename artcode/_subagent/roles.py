from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

import yaml

from artcode.core.subagent import RoleCatalogSnapshot, RoleDiagnostic, RoleSource, RoleSummary
from artcode.core.tool import PermissionMode, ToolDescriptor, ToolEffect


NAME = re.compile(r"[a-z][a-z0-9-]{0,31}\Z")


@dataclass(frozen=True, slots=True)
class Role:
    name: str
    description: str
    source: RoleSource
    allow: frozenset[str]
    deny: frozenset[str]
    model: str
    max_rounds: int
    permission_mode: PermissionMode
    isolation: str
    sop: str


def discover_roles(
    project: Path,
    user: Path,
    builtin: Path,
    extensions: tuple[Path, ...],
    descriptors: tuple[ToolDescriptor, ...],
    model_tiers: dict[str, str],
) -> tuple[dict[str, Role], RoleCatalogSnapshot]:
    sources = (
        (RoleSource.PROJECT, (project,)),
        (RoleSource.USER, (user,)),
        (RoleSource.BUILTIN, (builtin,)),
        (RoleSource.EXTENSION, extensions),
    )
    candidates: dict[RoleSource, dict[str, list[Path]]] = {}
    for source, roots in sources:
        grouped: dict[str, list[Path]] = {}
        for root in roots:
            if not root.exists() or root.is_symlink() or not root.is_dir():
                continue
            for path in sorted(root.glob("*.md")):
                grouped.setdefault(path.stem, []).append(path)
        candidates[source] = grouped
    names = sorted({name for grouped in candidates.values() for name in grouped})
    selected: dict[str, Role] = {}
    diagnostics: list[RoleDiagnostic] = []
    descriptor_by_name = {item.name: item for item in descriptors}
    for name in names:
        for source, _ in sources:
            paths = candidates[source].get(name, [])
            if not paths:
                continue
            if len(paths) != 1:
                diagnostics.append(RoleDiagnostic(name, source, "同一来源 Role 重复，已阻断回退。"))
                break
            try:
                selected[name] = _parse(paths[0], source, name, descriptor_by_name, model_tiers)
            except (OSError, UnicodeDecodeError, ValueError) as exc:
                diagnostics.append(RoleDiagnostic(name, source, f"高优先级 Role 无效并阻断回退：{exc}"))
            break
    snapshot = RoleCatalogSnapshot(
        tuple(RoleSummary(item.name, item.description, item.source) for _, item in sorted(selected.items())),
        tuple(diagnostics),
    )
    return selected, snapshot


def _parse(
    path: Path,
    source: RoleSource,
    logical_name: str,
    descriptors: dict[str, ToolDescriptor],
    model_tiers: dict[str, str],
) -> Role:
    if path.is_symlink() or not path.is_file():
        raise ValueError("Role 必须是普通 Markdown 文件。")
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError("Role 缺少 frontmatter。")
    lines = text.splitlines(keepends=True)
    end = next((index for index, line in enumerate(lines[1:], 1) if line.strip() == "---"), None)
    if end is None:
        raise ValueError("Role frontmatter 未闭合。")
    raw = yaml.safe_load("".join(lines[1:end]))
    sop = "".join(lines[end + 1 :])
    allowed_fields = {"name", "description", "tools", "model", "max_rounds", "permission_mode", "isolation"}
    if not isinstance(raw, dict) or set(raw) != allowed_fields:
        raise ValueError("Role frontmatter 必须且只能包含七个规定字段。")
    name = raw["name"]
    if not isinstance(name, str) or NAME.fullmatch(name) is None or name != logical_name:
        raise ValueError("Role name 必须是与文件名一致的小写安全标识。")
    description = raw["description"]
    if not isinstance(description, str) or not description.strip() or "\n" in description:
        raise ValueError("Role description 必须是单行非空文本。")
    tools = raw["tools"]
    if not isinstance(tools, dict) or set(tools) != {"allow", "deny"}:
        raise ValueError("Role tools 必须包含 allow 和 deny。")
    allow = _tool_names(tools["allow"])
    deny = _tool_names(tools["deny"])
    if allow & deny:
        raise ValueError("Role Tool 不能同时 allow 和 deny。")
    unknown = (allow | deny) - set(descriptors)
    forbidden = {name for name in allow | deny if name.startswith("mcp__") or name in {"agent", "task_list", "task_get", "task_cancel", "load_skill"}}
    if unknown or forbidden:
        raise ValueError(f"Role 引用未知或禁止 Tool：{', '.join(sorted(unknown | forbidden))}")
    model = raw["model"]
    if model not in {"inherit", "haiku", "sonnet", "opus"}:
        raise ValueError("Role model 档位无效。")
    if model != "inherit" and not model_tiers.get(model):
        raise ValueError(f"Role model 档位未映射：{model}")
    rounds = raw["max_rounds"]
    if isinstance(rounds, bool) or not isinstance(rounds, int) or not 1 <= rounds <= 100:
        raise ValueError("Role max_rounds 必须为 1～100。")
    try:
        permission = PermissionMode(raw["permission_mode"])
    except (TypeError, ValueError) as exc:
        raise ValueError("Role permission_mode 无效。") from exc
    isolation = raw["isolation"]
    if isolation not in {"none", "worktree"}:
        raise ValueError("Role isolation 只能是 none 或 worktree。")
    has_effect = any(descriptors[name].effect is not ToolEffect.OBSERVE for name in allow)
    if has_effect and isolation != "worktree":
        raise ValueError("含写入或 Shell Tool 的 Role 必须使用 worktree。")
    if not sop.strip():
        raise ValueError("Role SOP 不能为空。")
    return Role(name, description.strip(), source, allow, deny, model, rounds, permission, isolation, sop)


def _tool_names(raw: Any) -> frozenset[str]:
    if not isinstance(raw, list) or any(not isinstance(item, str) or not item for item in raw):
        raise ValueError("Role allow/deny 必须是工具名列表。")
    if len(set(raw)) != len(raw):
        raise ValueError("Role allow/deny 不能重复。")
    return frozenset(raw)


def effective_capabilities(
    parent: frozenset[str],
    allow: frozenset[str],
    deny: frozenset[str],
    background: frozenset[str],
) -> frozenset[str]:
    forbidden = {"agent", "task_list", "task_get", "task_cancel", "load_skill"}
    return frozenset((parent & allow & background) - deny - forbidden)
