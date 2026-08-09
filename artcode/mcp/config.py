from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

import yaml

from .models import McpConfigIssue, McpServerConfig, ServerSource, TransportKind


VARIABLE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
PROJECT_CONFIG_PATH = Path(".artcode") / "config.yml"
BASE_ENV_NAMES = ("PATH", "HOME", "USER", "TMPDIR", "LANG", "LC_ALL", "SHELL", "SYSTEMROOT", "WINDIR")


def load_project_raw(workspace: Path) -> tuple[dict[str, Any], str | None]:
    path = workspace / PROJECT_CONFIG_PATH
    if not path.exists():
        return {}, None
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        return {}, f"项目 MCP 配置无法读取：{exc}"
    if not isinstance(raw, dict):
        return {}, "项目配置顶层必须是对象/map。"
    extra = sorted(set(raw) - {"mcp_servers"})
    if extra:
        return {}, f"项目配置只允许 mcp_servers，发现：{', '.join(extra)}"
    return raw, None


def load_mcp_configuration(
    user_raw: Mapping[str, Any],
    workspace: Path,
) -> tuple[tuple[McpServerConfig, ...], tuple[McpConfigIssue, ...]]:
    project_raw, project_error = load_project_raw(workspace)
    issues: list[McpConfigIssue] = []
    if project_error:
        issues.append(McpConfigIssue("<project>", project_error, ServerSource.PROJECT))
    merged: dict[str, tuple[Any, ServerSource]] = {}
    for source_raw, source in ((user_raw, ServerSource.USER), (project_raw, ServerSource.PROJECT)):
        servers = source_raw.get("mcp_servers", {})
        if servers is None:
            continue
        if not isinstance(servers, Mapping):
            issues.append(McpConfigIssue("<config>", "mcp_servers 必须是对象/map。", source))
            continue
        for name, value in servers.items():
            if not isinstance(name, str) or not name.strip():
                issues.append(McpConfigIssue(str(name), "Server 名必须是非空字符串。", source))
                continue
            merged[name] = (value, source)

    configs: list[McpServerConfig] = []
    for name, (raw, source) in merged.items():
        try:
            configs.append(_parse_server(name, raw, source))
        except ValueError as exc:
            issues.append(McpConfigIssue(name, str(exc), source))
    return tuple(configs), tuple(issues)


def _parse_server(name: str, raw: Any, source: ServerSource) -> McpServerConfig:
    if not isinstance(raw, dict):
        raise ValueError("Server 配置必须是对象/map。")
    transport_raw = raw.get("transport")
    try:
        transport = TransportKind(transport_raw)
    except (ValueError, TypeError):
        raise ValueError("transport 必须是 stdio 或 streamable_http。") from None
    allowed = (
        {"transport", "enabled", "command", "args", "env"}
        if transport is TransportKind.STDIO
        else {"transport", "enabled", "url", "headers"}
    )
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ValueError(f"包含未知或混用字段：{', '.join(unknown)}")
    enabled = raw.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ValueError("enabled 必须是布尔值。")
    if transport is TransportKind.STDIO:
        command = _non_empty(raw.get("command"), "command")
        args = _string_list(raw.get("args", []), "args")
        env = _string_map(raw.get("env", {}), "env")
        values = [command, *args, *env.values()]
        return McpServerConfig(
            name, transport, source, enabled, command=command, args=tuple(args), env=env,
            referenced_variables=_variables(values),
        )
    url = _non_empty(raw.get("url"), "url")
    if urlparse(url).scheme not in {"http", "https"}:
        raise ValueError("url 只支持 http 或 https。")
    headers = _string_map(raw.get("headers", {}), "headers")
    return McpServerConfig(
        name, transport, source, enabled, url=url, headers=headers,
        referenced_variables=_variables([url, *headers.values()]),
    )


def expand_config(config: McpServerConfig, environ: Mapping[str, str] | None = None) -> McpServerConfig:
    source = os.environ if environ is None else environ
    missing = [name for name in config.referenced_variables if name not in source]
    if missing:
        raise ValueError(f"缺少环境变量：{', '.join(missing)}")

    def expand(value: str) -> str:
        return VARIABLE.sub(lambda match: source[match.group(1)], value)

    return McpServerConfig(
        name=config.name,
        transport=config.transport,
        source=config.source,
        enabled=config.enabled,
        command=expand(config.command) if config.command else None,
        args=tuple(expand(item) for item in config.args),
        env={key: expand(value) for key, value in config.env.items()},
        url=expand(config.url) if config.url else None,
        headers={key: expand(value) for key, value in config.headers.items()},
        referenced_variables=config.referenced_variables,
    )


def safe_stdio_environment(config_env: Mapping[str, str], environ: Mapping[str, str] | None = None) -> dict[str, str]:
    source = os.environ if environ is None else environ
    result = {name: source[name] for name in BASE_ENV_NAMES if name in source}
    result.update(config_env)
    return result


def _non_empty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} 必须是非空字符串。")
    return value.strip()


def _string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{field} 必须是字符串列表。")
    return value


def _string_map(value: Any, field: str) -> dict[str, str]:
    if not isinstance(value, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in value.items()):
        raise ValueError(f"{field} 必须是字符串到字符串的对象/map。")
    return dict(value)


def _variables(values: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(match.group(1) for value in values for match in VARIABLE.finditer(value)))
