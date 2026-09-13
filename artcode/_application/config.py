from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from artcode.core.model import ModelSettings
from artcode.core.tool import McpLoading, PermissionMode, ShellPolicy


class ConfigurationFailure(ValueError):
    def __init__(self, issues: list[str]) -> None:
        self.issues = tuple(issues)
        super().__init__("配置无效：\n" + "\n".join(f"- {item}" for item in issues))


@dataclass(frozen=True, slots=True)
class LoadedConfig:
    model: ModelSettings
    context_window_tokens: int
    permission_mode: PermissionMode
    shell_policy: ShellPolicy
    mcp_loading: McpLoading
    user_mcp: dict[str, Any]
    project_mcp: dict[str, Any]
    model_tiers: dict[str, str]
    background_tools: frozenset[str] | None


TOP = {
    "protocol", "model", "base_url", "api_key", "thinking", "context", "permissions",
    "mcp", "mcp_servers", "agents",
}


def load_config(user_path: Path, project_path: Path) -> LoadedConfig:
    issues: list[str] = []
    user = _read(user_path, "用户配置", issues, required=True)
    project = _read(project_path, "项目配置", issues, required=False)
    for label, raw in (("用户配置", user), ("项目配置", project)):
        unknown = set(raw) - TOP
        if unknown:
            issues.append(f"{label}包含未知字段：{', '.join(sorted(unknown))}")
    merged = _merge(user, project)
    protocol = _string(merged, "protocol", issues)
    model = _string(merged, "model", issues)
    base_url = _string(merged, "base_url", issues)
    api_key = _string(merged, "api_key", issues)
    if protocol and protocol != "openai":
        issues.append("protocol 目前只能是 openai")
    thinking = _mapping(merged.get("thinking", {}), "thinking", issues)
    thinking_enabled = thinking.get("enabled", False)
    if not isinstance(thinking_enabled, bool):
        issues.append("thinking.enabled 必须是布尔值")
        thinking_enabled = False
    context = _mapping(merged.get("context", {}), "context", issues)
    window = context.get("window_tokens", 1_000_000)
    if isinstance(window, bool) or not isinstance(window, int) or window < 1:
        issues.append("context.window_tokens 必须是正整数")
        window = 1_000_000
    permissions = _mapping(merged.get("permissions", {}), "permissions", issues)
    try:
        permission_mode = PermissionMode(permissions.get("mode", "default"))
    except (TypeError, ValueError):
        issues.append("permissions.mode 只能是 default、edit 或 full")
        permission_mode = PermissionMode.DEFAULT
    try:
        shell_policy = ShellPolicy(permissions.get("shell", "sandbox_auto"))
    except (TypeError, ValueError):
        issues.append("permissions.shell 只能是 sandbox_auto、sandbox_ask 或 explicit_unsafe")
        shell_policy = ShellPolicy.SANDBOX_AUTO
    mcp = _mapping(merged.get("mcp", {}), "mcp", issues)
    try:
        loading = McpLoading(mcp.get("loading", "eager"))
    except (TypeError, ValueError):
        issues.append("mcp.loading 只能是 eager 或 lazy")
        loading = McpLoading.EAGER
    user_mcp = _mapping(user.get("mcp_servers", {}), "用户 mcp_servers", issues)
    project_mcp = _mapping(project.get("mcp_servers", {}), "项目 mcp_servers", issues)
    agents = _mapping(merged.get("agents", {}), "agents", issues)
    tiers = _mapping(agents.get("models", {}), "agents.models", issues)
    model_tiers: dict[str, str] = {}
    for tier, value in tiers.items():
        if tier not in {"haiku", "sonnet", "opus"} or not isinstance(value, str) or not value.strip():
            issues.append(f"agents.models.{tier} 无效")
        else:
            model_tiers[tier] = value.strip()
    background_raw = agents.get("background_tools")
    background = None
    if background_raw is not None:
        if not isinstance(background_raw, list) or any(not isinstance(item, str) for item in background_raw):
            issues.append("agents.background_tools 必须是工具名列表")
        else:
            background = frozenset(background_raw)
    if issues:
        raise ConfigurationFailure(issues)
    return LoadedConfig(
        ModelSettings(model, base_url, api_key, thinking_enabled),
        window,
        permission_mode,
        shell_policy,
        loading,
        dict(user_mcp),
        dict(project_mcp),
        model_tiers,
        background,
    )


def _read(path: Path, label: str, issues: list[str], *, required: bool) -> dict[str, Any]:
    if not path.exists():
        if required:
            issues.append(f"{label}不存在：{path}")
        return {}
    if path.is_symlink() or not path.is_file():
        issues.append(f"{label}必须是普通文件")
        return {}
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        issues.append(f"{label}无法读取：{exc}")
        return {}
    if not isinstance(raw, dict):
        issues.append(f"{label}顶层必须是对象")
        return {}
    return raw


def _merge(user: dict[str, Any], project: dict[str, Any]) -> dict[str, Any]:
    merged = dict(user)
    for key, value in project.items():
        if key == "mcp_servers":
            continue
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
    return merged


def _string(raw: dict[str, Any], key: str, issues: list[str]) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        issues.append(f"{key} 必须是非空字符串")
        return "invalid"
    return value.strip()


def _mapping(value: Any, name: str, issues: list[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        issues.append(f"{name} 必须是对象")
        return {}
    return value
