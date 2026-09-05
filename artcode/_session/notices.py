from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import tempfile
import uuid

from artcode.core.model import Usage


@dataclass
class DerivedState:
    notices: list[tuple[str, str]] = field(default_factory=list)
    summary: str | None = None
    summary_through: int = 0
    latest_plan: str | None = None
    last_usage: Usage | None = None


class DerivedStateStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> tuple[DerivedState, tuple[str, ...]]:
        if not self.path.exists():
            return DerivedState(), ()
        try:
            if self.path.is_symlink() or not self.path.is_file():
                raise ValueError("派生状态不是可信普通文件")
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict) or set(raw) != {
                "version", "notices", "summary", "summary_through", "latest_plan", "last_usage"
            } or raw["version"] != 1:
                raise ValueError("派生状态字段或版本无效")
            notices = []
            for item in raw["notices"]:
                if not isinstance(item, dict) or set(item) != {"id", "text"}:
                    raise ValueError("Notice 结构无效")
                if not isinstance(item["id"], str) or not isinstance(item["text"], str):
                    raise ValueError("Notice 字段类型无效")
                notices.append((item["id"], item["text"]))
            summary = raw["summary"]
            latest_plan = raw["latest_plan"]
            if summary is not None and not isinstance(summary, str):
                raise ValueError("Summary 类型无效")
            if latest_plan is not None and not isinstance(latest_plan, str):
                raise ValueError("计划类型无效")
            through = raw["summary_through"]
            if isinstance(through, bool) or not isinstance(through, int) or through < 0:
                raise ValueError("Summary 范围无效")
            usage_raw = raw["last_usage"]
            usage = None
            if usage_raw is not None:
                if not isinstance(usage_raw, dict):
                    raise ValueError("usage 类型无效")
                usage = Usage(
                    usage_raw.get("input_tokens"),
                    usage_raw.get("output_tokens"),
                    usage_raw.get("total_tokens"),
                    usage_raw.get("cached_tokens"),
                    usage_raw.get("cache_miss_tokens"),
                )
            return DerivedState(notices, summary, through, latest_plan, usage), ()
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            return DerivedState(), (f"派生状态损坏，已忽略：{exc}",)

    def save(self, state: DerivedState) -> None:
        payload = {
            "version": 1,
            "notices": [{"id": identifier, "text": text} for identifier, text in state.notices],
            "summary": state.summary,
            "summary_through": state.summary_through,
            "latest_plan": state.latest_plan,
            "last_usage": (
                {
                    "input_tokens": state.last_usage.input_tokens,
                    "output_tokens": state.last_usage.output_tokens,
                    "total_tokens": state.last_usage.total_tokens,
                    "cached_tokens": state.last_usage.cached_tokens,
                    "cache_miss_tokens": state.last_usage.cache_miss_tokens,
                }
                if state.last_usage is not None
                else None
            ),
        }
        if self.path.is_symlink() or self.path.parent.is_symlink():
            raise ValueError("派生状态路径不能是符号链接。")
        temporary: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=self.path.parent, prefix=".state-", delete=False
            ) as handle:
                temporary = handle.name
                os.chmod(temporary, 0o600)
                json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            temporary = None
            os.chmod(self.path, 0o600)
        finally:
            if temporary is not None:
                Path(temporary).unlink(missing_ok=True)


def add_notice(state: DerivedState, text: str) -> str:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Notice 必须是非空字符串。")
    identifier = uuid.uuid4().hex
    state.notices.append((identifier, text))
    return identifier
