from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .errors import ConfigError, mask_secret


CONFIG_FILENAME = "artcode.yaml"
CHAPTER_NAME = "ch04：动手实现 Agent Loop"
SUPPORTED_PROTOCOL = "openai"
SUPPORTED_THINKING_EFFORTS = {"low", "medium", "high"}
DEFAULT_ALLOWED_DIR = Path("/Users/arthalter/Work/ArtCode/实验场")


@dataclass(frozen=True)
class ThinkingConfig:
    enabled: bool = False
    effort: str = "high"


@dataclass(frozen=True)
class ToolConfig:
    allowed_dirs: tuple[Path, ...] = (DEFAULT_ALLOWED_DIR,)


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
    allowed_dirs: tuple[str, ...]


@dataclass(frozen=True)
class ArtCodeConfig:
    protocol: str
    model: str
    base_url: str
    api_key: str
    thinking: ThinkingConfig
    tools: ToolConfig = ToolConfig()

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
            allowed_dirs=tuple(str(path) for path in self.tools.allowed_dirs),
        )


def load_config(config_path: Path | str | None = None) -> ArtCodeConfig:
    path = Path(config_path) if config_path is not None else Path.cwd() / CONFIG_FILENAME
    if not path.exists():
        raise ConfigError(
            f"找不到配置文件 {CONFIG_FILENAME}。",
            "请复制 artcode.example.yaml 为 artcode.yaml，并填写 DeepSeek API key。",
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

    thinking = _parse_thinking(raw.get("thinking"))
    tools = _parse_tools(raw.get("tools"))
    return ArtCodeConfig(
        protocol=protocol,
        model=model,
        base_url=base_url,
        api_key=api_key,
        thinking=thinking,
        tools=tools,
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


def _parse_tools(raw: Any) -> ToolConfig:
    if raw is None:
        return _tool_config_from_allowed_dirs([DEFAULT_ALLOWED_DIR])
    if not isinstance(raw, dict):
        raise ConfigError("配置字段 tools 必须是对象/map。")

    allowed_dirs = raw.get("allowed_dirs")
    if allowed_dirs is None:
        return _tool_config_from_allowed_dirs([DEFAULT_ALLOWED_DIR])
    if not isinstance(allowed_dirs, list):
        raise ConfigError("配置字段 tools.allowed_dirs 必须是列表。")
    if not allowed_dirs:
        raise ConfigError("配置字段 tools.allowed_dirs 不能为空列表。")

    return _tool_config_from_allowed_dirs(allowed_dirs)


def _tool_config_from_allowed_dirs(raw_dirs: list[Any]) -> ToolConfig:
    parsed: list[Path] = []
    for value in raw_dirs:
        if not isinstance(value, (str, Path)):
            raise ConfigError("配置字段 tools.allowed_dirs 的每一项都必须是绝对路径字符串。")
        path_text = str(value).strip()
        if not path_text:
            raise ConfigError("配置字段 tools.allowed_dirs 不能包含空路径。")
        path = Path(path_text).expanduser()
        if not path.is_absolute():
            raise ConfigError("配置字段 tools.allowed_dirs 只支持绝对路径。")
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ConfigError(
                f"无法创建允许目录：{path}。",
                "请检查目录路径是否正确，以及当前用户是否有权限创建该目录。",
            ) from exc
        parsed.append(path.resolve())

    return ToolConfig(allowed_dirs=tuple(parsed))
