from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
import re
from typing import Any, Mapping
from urllib.parse import urlparse

from artcode.core.tool import McpServerReport, McpServerSource, McpServerState


VARIABLE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
BASE_ENV = ("PATH", "HOME", "USER", "TMPDIR", "LANG", "LC_ALL", "SHELL")


@dataclass(frozen=True, slots=True)
class ServerConfig:
    name: str
    source: McpServerSource
    transport: str
    enabled: bool
    command: str | None = None
    args: tuple[str, ...] = ()
    env: tuple[tuple[str, str], ...] = ()
    url: str | None = None
    headers: tuple[tuple[str, str], ...] = ()

    @property
    def secrets(self) -> tuple[str, ...]:
        return tuple(value for _, value in (*self.env, *self.headers) if value)

    @property
    def summary(self) -> str:
        return f"{self.transport}: {self.command or self.url or ''}"


def load_configs(
    user: Mapping[str, Any],
    project: Mapping[str, Any],
    *,
    environ: Mapping[str, str] | None = None,
) -> tuple[tuple[ServerConfig, ...], tuple[McpServerReport, ...]]:
    source_env = os.environ if environ is None else environ
    merged: dict[str, tuple[Any, McpServerSource]] = {}
    issues: list[McpServerReport] = []
    for raw, source in ((user, McpServerSource.USER), (project, McpServerSource.PROJECT)):
        if not isinstance(raw, Mapping):
            issues.append(McpServerReport("<config>", source, McpServerState.INVALID, detail="MCP 配置必须是对象。"))
            continue
        for name, value in raw.items():
            if not isinstance(name, str) or not name.strip():
                issues.append(McpServerReport(str(name), source, McpServerState.INVALID, detail="Server 名必须是非空字符串。"))
                continue
            merged[name] = (value, source)
    configs: list[ServerConfig] = []
    for name, (raw, source) in merged.items():
        try:
            configs.append(_parse(name, raw, source, source_env))
        except ValueError as exc:
            issues.append(McpServerReport(name, source, McpServerState.INVALID, detail=str(exc)))
    return tuple(configs), tuple(issues)


def _parse(
    name: str,
    raw: Any,
    source: McpServerSource,
    environ: Mapping[str, str],
) -> ServerConfig:
    if not isinstance(raw, dict):
        raise ValueError("Server 配置必须是对象。")
    transport = raw.get("transport")
    if transport not in {"stdio", "streamable_http"}:
        raise ValueError("transport 必须是 stdio 或 streamable_http。")
    allowed = (
        {"transport", "enabled", "command", "args", "env"}
        if transport == "stdio"
        else {"transport", "enabled", "url", "headers"}
    )
    unknown = set(raw) - allowed
    if unknown:
        raise ValueError(f"包含未知或混用字段：{', '.join(sorted(unknown))}")
    enabled = raw.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ValueError("enabled 必须是布尔值。")
    if transport == "stdio":
        command = _text(raw.get("command"), "command")
        args = _string_list(raw.get("args", []), "args")
        env = _string_map(raw.get("env", {}), "env")
        values = [command, *args, *env.values()]
        expanded = [_expand(value, environ) for value in values] if enabled else values
        return ServerConfig(
            name,
            source,
            transport,
            enabled,
            command=expanded[0],
            args=tuple(expanded[1 : 1 + len(args)]),
            env=tuple((key, _expand(value, environ) if enabled else value) for key, value in env.items()),
        )
    raw_url = _text(raw.get("url"), "url")
    url = _expand(raw_url, environ) if enabled else raw_url
    if urlparse(url).scheme not in {"http", "https"}:
        raise ValueError("url 只支持 http 或 https。")
    headers = _string_map(raw.get("headers", {}), "headers")
    return ServerConfig(
        name,
        source,
        transport,
        enabled,
        url=url,
        headers=tuple((key, _expand(value, environ) if enabled else value) for key, value in headers.items()),
    )


def safe_environment(config: ServerConfig) -> dict[str, str]:
    result = {key: os.environ[key] for key in BASE_ENV if key in os.environ}
    result.update(dict(config.env))
    return result


def registered_name(server: str, tool: str) -> str:
    def normalize(value: str) -> str:
        normalized = re.sub(r"[^A-Za-z0-9_-]+", "_", value.strip())
        return re.sub(r"_+", "_", normalized).strip("_") or "unnamed"

    raw = f"mcp__{normalize(server)}__{normalize(tool)}"
    if len(raw) <= 64:
        return raw
    suffix = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:10]
    return f"{raw[:52]}__{suffix}"


def _expand(value: str, environ: Mapping[str, str]) -> str:
    missing = [match.group(1) for match in VARIABLE.finditer(value) if match.group(1) not in environ]
    if missing:
        raise ValueError(f"缺少环境变量：{', '.join(dict.fromkeys(missing))}")
    return VARIABLE.sub(lambda match: environ[match.group(1)], value)


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} 必须是非空字符串。")
    return value.strip()


def _string_list(value: Any, name: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{name} 必须是字符串列表。")
    return value


def _string_map(value: Any, name: str) -> dict[str, str]:
    if not isinstance(value, dict) or any(not isinstance(key, str) or not isinstance(item, str) for key, item in value.items()):
        raise ValueError(f"{name} 必须是字符串映射。")
    return dict(value)
