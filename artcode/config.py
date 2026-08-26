from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

import yaml

from .errors import ConfigError
from .mcp.models import McpLoadingStrategy


CONFIG_FILENAME = "config.yml"
SUPPORTED_PROTOCOL = "openai"
DEFAULT_CONTEXT_WINDOW_TOKENS = 1_000_000
MIN_CONTEXT_WINDOW_TOKENS = 200_000
MAX_CONTEXT_WINDOW_TOKENS = 1_000_000
_TOP_LEVEL_FIELDS = frozenset(
    {
        "protocol", "model", "base_url", "api_key", "thinking", "context", "mcp",
        "mcp_servers", "agents",
    }
)
_THINKING_FIELDS = frozenset({"enabled"})
_CONTEXT_FIELDS = frozenset({"window_tokens"})
_MCP_FIELDS = frozenset({"loading"})
_AGENT_FIELDS = frozenset({"models", "background_tools"})
_AGENT_MODEL_FIELDS = frozenset({"haiku", "sonnet", "opus"})
DEFAULT_BACKGROUND_TOOLS = (
    "read_file",
    "write_file",
    "edit_file",
    "run_command",
    "find_files",
    "search_text",
)


@dataclass(frozen=True)
class ThinkingConfig:
    enabled: bool = False


@dataclass(frozen=True)
class ContextConfig:
    window_tokens: int = DEFAULT_CONTEXT_WINDOW_TOKENS

    @property
    def automatic_threshold(self) -> int:
        return self.window_tokens * 167 // 200

    @property
    def forced_threshold(self) -> int:
        return self.window_tokens * 177 // 200


@dataclass(frozen=True)
class AgentConfig:
    """Configuration intentionally limited to stable, logical model tiers.

    Background concurrency and the foreground grace period are protocol
    guarantees, rather than user-tunable knobs: four tasks and 120 seconds.
    """

    models: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    background_tools: tuple[str, ...] = DEFAULT_BACKGROUND_TOOLS
    max_concurrent_tasks: int = 4
    foreground_timeout_seconds: float = 120.0


@dataclass(frozen=True)
class ArtCodeConfig:
    protocol: str
    model: str
    base_url: str
    api_key: str
    thinking: ThinkingConfig
    mcp_servers_raw: Mapping[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )
    context: ContextConfig = ContextConfig()
    mcp_loading: McpLoadingStrategy = McpLoadingStrategy.EAGER
    agents: AgentConfig = AgentConfig()


def load_config(config_path: Path | str | None = None) -> ArtCodeConfig:
    path = Path(config_path) if config_path is not None else Path.home() / ".artcode" / CONFIG_FILENAME
    if not path.exists():
        raise ConfigError(
            f"找不到配置文件 {path}。",
            "请复制 config.example.yml 到 ~/.artcode/config.yml，并填写模型、服务地址和 API key。",
        )

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(
            f"配置文件 {path} 不是合法 YAML。",
            f"请检查缩进、冒号和引号。解析器提示：{exc}",
        ) from exc

    return parse_config(raw)


def parse_config(raw: Any) -> ArtCodeConfig:
    if not isinstance(raw, dict):
        raise ConfigError("配置结构错误：YAML 顶层必须是对象/map。")

    _reject_unknown_keys(raw, _TOP_LEVEL_FIELDS, "配置顶层")
    protocol = _required_non_empty_string(raw, "protocol")
    model = _required_non_empty_string(raw, "model")
    base_url = _required_non_empty_string(raw, "base_url")
    api_key = _required_non_empty_string(raw, "api_key")

    if protocol != SUPPORTED_PROTOCOL:
        raise ConfigError(
            f"当前不支持 protocol: {protocol}。",
            f"ArtCode 目前只支持 protocol: {SUPPORTED_PROTOCOL}。",
        )

    return ArtCodeConfig(
        protocol=protocol,
        model=model,
        base_url=base_url,
        api_key=api_key,
        thinking=_parse_thinking(raw.get("thinking")),
        context=_parse_context(raw.get("context")),
        mcp_servers_raw=_parse_mcp_servers(raw),
        mcp_loading=_parse_mcp(raw.get("mcp")),
        agents=_parse_agents(raw.get("agents")),
    )


def _required_non_empty_string(raw: dict[str, Any], key: str) -> str:
    if key not in raw:
        raise ConfigError(f"配置缺少字段：{key}。")
    value = raw[key]
    if not isinstance(value, str):
        raise ConfigError(f"配置字段 {key} 必须是字符串。")
    if not value.strip():
        raise ConfigError(f"配置字段 {key} 不能为空字符串。")
    return value.strip()


def _optional_non_empty_string(raw: dict[str, Any], key: str, default: str) -> str:
    if key not in raw:
        return default
    return _required_non_empty_string(raw, key)


def _parse_thinking(raw: Any) -> ThinkingConfig:
    if raw is None:
        return ThinkingConfig()
    if not isinstance(raw, dict):
        raise ConfigError("配置字段 thinking 必须是对象/map。")
    _reject_unknown_keys(raw, _THINKING_FIELDS, "配置字段 thinking")

    enabled = raw.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ConfigError("配置字段 thinking.enabled 必须是布尔值。")
    return ThinkingConfig(enabled=enabled)


def _parse_context(raw: Any) -> ContextConfig:
    if raw is None:
        return ContextConfig()
    if not isinstance(raw, dict):
        raise ConfigError("配置字段 context 必须是对象/map。")
    _reject_unknown_keys(raw, _CONTEXT_FIELDS, "配置字段 context")

    value = raw.get("window_tokens", DEFAULT_CONTEXT_WINDOW_TOKENS)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError("配置字段 context.window_tokens 必须是整数。")
    if not MIN_CONTEXT_WINDOW_TOKENS <= value <= MAX_CONTEXT_WINDOW_TOKENS:
        raise ConfigError(
            "配置字段 context.window_tokens 必须在 "
            f"{MIN_CONTEXT_WINDOW_TOKENS} 到 {MAX_CONTEXT_WINDOW_TOKENS} 之间。"
        )
    return ContextConfig(window_tokens=value)


def _parse_mcp_servers(raw: dict[str, Any]) -> Mapping[str, Any]:
    if "mcp_servers" not in raw:
        return MappingProxyType({})
    value = raw["mcp_servers"]
    if not isinstance(value, dict):
        raise ConfigError("配置字段 mcp_servers 必须是对象/map。")
    return MappingProxyType(dict(value))


def _parse_mcp(raw: Any) -> McpLoadingStrategy:
    if raw is None:
        return McpLoadingStrategy.EAGER
    if not isinstance(raw, dict):
        raise ConfigError("配置字段 mcp 必须是对象/map。")
    _reject_unknown_keys(raw, _MCP_FIELDS, "配置字段 mcp")
    value = raw.get("loading", McpLoadingStrategy.EAGER.value)
    try:
        return McpLoadingStrategy(value)
    except (TypeError, ValueError):
        raise ConfigError("配置字段 mcp.loading 只能是 eager 或 lazy。") from None


def _parse_agents(raw: Any) -> AgentConfig:
    if raw is None:
        return AgentConfig()
    if not isinstance(raw, dict):
        raise ConfigError("配置字段 agents 必须是对象/map。")
    _reject_unknown_keys(raw, _AGENT_FIELDS, "配置字段 agents")
    tiers = raw.get("models", {})
    if not isinstance(tiers, dict):
        raise ConfigError("配置字段 agents.models 必须是对象/map。")
    _reject_unknown_keys(tiers, _AGENT_MODEL_FIELDS, "配置字段 agents.models")
    normalized: dict[str, str] = {}
    for tier, model in tiers.items():
        if not isinstance(model, str) or not model.strip():
            raise ConfigError(f"agents.models.{tier} 必须是非空模型名。")
        normalized[tier] = model.strip()
    tools = raw.get("background_tools", list(DEFAULT_BACKGROUND_TOOLS))
    if not isinstance(tools, list) or any(not isinstance(item, str) or not item for item in tools):
        raise ConfigError("配置字段 agents.background_tools 必须是工具名字符串列表。")
    if len(set(tools)) != len(tools):
        raise ConfigError("配置字段 agents.background_tools 不能包含重复工具。")
    unknown_tools = sorted(set(tools) - set(DEFAULT_BACKGROUND_TOOLS))
    if unknown_tools:
        raise ConfigError(
            "配置字段 agents.background_tools 只能收窄默认安全工具集合；"
            f"不允许：{'、'.join(unknown_tools)}。"
        )
    return AgentConfig(MappingProxyType(normalized), tuple(tools))


def _reject_unknown_keys(raw: Mapping[str, Any], allowed: frozenset[str], path: str) -> None:
    unknown = sorted(str(key) for key in raw if key not in allowed)
    if unknown:
        raise ConfigError(f"{path}包含未知字段：{'、'.join(unknown)}。")
