from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from .errors import ConfigError, mask_secret


CONFIG_FILENAME = "config.yml"
CHAPTER_NAME = "ch09：会话恢复与长期记忆"
SUPPORTED_PROTOCOL = "openai"
SUPPORTED_THINKING_EFFORTS = {"low", "medium", "high"}
DEFAULT_CONTEXT_WINDOW_TOKENS = 200_000
MIN_CONTEXT_WINDOW_TOKENS = 200_000
MAX_CONTEXT_WINDOW_TOKENS = 1_000_000


@dataclass(frozen=True)
class ThinkingConfig:
    enabled: bool = False
    effort: str = "high"


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
class SafeConfigStatus:
    chapter: str
    protocol: str
    model: str
    base_url: str
    streaming: bool
    thinking_enabled: bool
    thinking_effort: str
    masked_api_key: str
    workspace: str = ""
    permission_mode: str = "default"
    shell_policy: str = "auto"
    seatbelt_status: str = "not initialized"
    context_window_tokens: int = DEFAULT_CONTEXT_WINDOW_TOKENS
    session_id: str = ""
    session_state: str = "disabled"
    recovered_messages: int = 0
    bad_session_lines: int = 0
    session_truncated: bool = False
    instruction_bytes: int = 0
    instruction_issues: int = 0
    user_active_notes: int = 0
    project_active_notes: int = 0


@dataclass(frozen=True)
class ArtCodeConfig:
    protocol: str
    model: str
    base_url: str
    api_key: str
    thinking: ThinkingConfig
    workspace: Path | None = None
    mcp_servers_raw: Mapping[str, Any] | None = None
    context: ContextConfig = ContextConfig()

    def safe_status(self) -> SafeConfigStatus:
        return SafeConfigStatus(
            chapter=CHAPTER_NAME,
            protocol=self.protocol,
            model=self.model,
            base_url=self.base_url,
            streaming=True,
            thinking_enabled=self.thinking.enabled,
            thinking_effort=self.thinking.effort,
            masked_api_key=mask_secret(self.api_key),
            context_window_tokens=self.context.window_tokens,
        )


def load_config(config_path: Path | str | None = None) -> ArtCodeConfig:
    path = Path(config_path) if config_path is not None else Path.home() / ".artcode" / CONFIG_FILENAME
    if not path.exists():
        raise ConfigError(
            f"找不到配置文件 {CONFIG_FILENAME}。",
            "请复制 config.example.yml 到 ~/.artcode/config.yml，并填写 DeepSeek API key。",
        )

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(
            f"{CONFIG_FILENAME} 不是合法 YAML。",
            f"请检查缩进、冒号和引号。解析器提示：{exc}",
        ) from exc

    return parse_config(raw)


def parse_config(raw: Any) -> ArtCodeConfig:
    if not isinstance(raw, dict):
        raise ConfigError("配置结构错误：YAML 顶层必须是对象/map。")

    protocol = _required_non_empty_string(raw, "protocol")
    model = _required_non_empty_string(raw, "model")
    base_url = _required_non_empty_string(raw, "base_url")
    api_key = _required_non_empty_string(raw, "api_key")

    if protocol != SUPPORTED_PROTOCOL:
        raise ConfigError(
            f"当前不支持 protocol: {protocol}。",
            f"ArtCode 目前只支持 protocol: {SUPPORTED_PROTOCOL}。",
        )

    if "tools" in raw:
        raise ConfigError("ch06 已移除 tools.allowed_dirs；请使用 --workspace 指定项目目录。")
    thinking = _parse_thinking(raw.get("thinking"))
    context = _parse_context(raw.get("context"))
    return ArtCodeConfig(
        protocol=protocol,
        model=model,
        base_url=base_url,
        api_key=api_key,
        thinking=thinking,
        context=context,
        mcp_servers_raw=raw.get("mcp_servers") if isinstance(raw.get("mcp_servers"), dict) else None,
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


def _parse_thinking(raw: Any) -> ThinkingConfig:
    if raw is None:
        return ThinkingConfig()
    if not isinstance(raw, dict):
        raise ConfigError("配置字段 thinking 必须是对象/map。")

    enabled = raw.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ConfigError("配置字段 thinking.enabled 必须是布尔值。")

    effort = raw.get("effort", "high")
    if not isinstance(effort, str):
        raise ConfigError("配置字段 thinking.effort 必须是字符串。")
    effort = effort.strip()
    if effort not in SUPPORTED_THINKING_EFFORTS:
        allowed = "、".join(sorted(SUPPORTED_THINKING_EFFORTS))
        raise ConfigError(f"配置字段 thinking.effort 只能是 {allowed} 之一。")

    return ThinkingConfig(enabled=enabled, effort=effort)


def _parse_context(raw: Any) -> ContextConfig:
    if raw is None:
        return ContextConfig()
    if not isinstance(raw, dict):
        raise ConfigError("配置字段 context 必须是对象/map。")

    value = raw.get("window_tokens", DEFAULT_CONTEXT_WINDOW_TOKENS)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError("配置字段 context.window_tokens 必须是整数。")
    if not MIN_CONTEXT_WINDOW_TOKENS <= value <= MAX_CONTEXT_WINDOW_TOKENS:
        raise ConfigError(
            "配置字段 context.window_tokens 必须在 "
            f"{MIN_CONTEXT_WINDOW_TOKENS} 到 {MAX_CONTEXT_WINDOW_TOKENS} 之间。"
        )
    return ContextConfig(window_tokens=value)
