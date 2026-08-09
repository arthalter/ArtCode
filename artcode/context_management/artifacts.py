from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from artcode.conversation import ConversationEntry
from artcode.workspace import Workspace

from .estimator import estimate_text_tokens


PERSISTED_OUTPUT_START = "<persisted-output>"
PERSISTED_OUTPUT_END = "</persisted-output>"
PREVIEW_PART_BYTES = 1_024


@dataclass(frozen=True)
class PersistedToolOutput:
    tool_call_id: str
    tool_name: str
    relative_path: str
    original_bytes: int
    estimated_tokens: int
    preview: str
    marker: str


class ContextArtifactStore:
    def __init__(self, workspace: Workspace | Path, session_id: str | None = None) -> None:
        self.workspace = workspace if isinstance(workspace, Workspace) else Workspace.from_path(workspace)
        selected_session_id = session_id or _new_session_id()
        if (
            selected_session_id in {"", ".", ".."}
            or _safe_component(selected_session_id) != selected_session_id
        ):
            raise ValueError("上下文会话 ID 包含不安全字符。")
        self.session_id = selected_session_id
        self.context_root = self.workspace.context_root
        self.session_dir = self.context_root / self.session_id
        self.tool_results_dir = self.session_dir / "tool-results"
        self._sequence = 0
        self._started = False

    @property
    def started(self) -> bool:
        return self._started

    def start(self) -> None:
        artcode_dir = self.workspace.root / ".artcode"
        if artcode_dir.is_symlink() or self.context_root.is_symlink():
            raise RuntimeError("上下文目录不能是符号链接。")
        self.context_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        resolved_root = self.context_root.resolve(strict=True)
        if self.workspace.root not in resolved_root.parents:
            raise RuntimeError("上下文目录必须位于 Workspace 内。")
        self._cleanup_stale_sessions()
        if self.session_dir.exists() or self.session_dir.is_symlink():
            raise RuntimeError(f"上下文会话目录已存在：{self.session_dir}")
        self.tool_results_dir.mkdir(parents=True, mode=0o700)
        os.chmod(self.session_dir, 0o700)
        os.chmod(self.tool_results_dir, 0o700)
        self._write_session_marker()
        self._started = True

    def persist(self, entry: ConversationEntry) -> PersistedToolOutput:
        if not self._started:
            raise RuntimeError("Artifact Store 尚未启动。")
        result = entry.raw_tool_result
        if result is None or entry.payload.get("role") != "tool":
            raise ValueError("只能保存带原始 ToolResult 的工具消息。")

        tool_call_id = str(entry.payload.get("tool_call_id", "unknown"))
        tool_name = str(entry.payload.get("name") or result.tool_name or "tool")
        self._sequence += 1
        filename = (
            f"{self._sequence:06d}-"
            f"{_safe_component(tool_name)}-{_safe_component(tool_call_id)}.txt"
        )
        target = self.tool_results_dir / filename
        content = result.content
        self._atomic_write(target, content)

        relative_path = self.workspace.relative_path(target)
        original_bytes = len(content.encode("utf-8"))
        estimated_tokens = estimate_text_tokens(content)
        preview = _preview(content)
        marker = _build_marker(
            tool_name=tool_name,
            status=result.status,
            error_code=result.error_code,
            original_bytes=original_bytes,
            estimated_tokens=estimated_tokens,
            relative_path=relative_path,
            preview=preview,
        )
        return PersistedToolOutput(
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            relative_path=relative_path,
            original_bytes=original_bytes,
            estimated_tokens=estimated_tokens,
            preview=preview,
            marker=marker,
        )

    def is_current_artifact(self, path: Path) -> bool:
        try:
            candidate = path.expanduser()
            if candidate.is_symlink():
                return False
            resolved = candidate.resolve(strict=True)
            root = self.tool_results_dir.resolve(strict=True)
        except OSError:
            return False
        return resolved.is_file() and root in resolved.parents

    def discard(self, persisted: PersistedToolOutput) -> None:
        target = self.workspace.root / persisted.relative_path
        if not self.is_current_artifact(target):
            return
        target.unlink(missing_ok=True)

    def close(self) -> None:
        if not self._started:
            return
        self._remove_session_dir(self.session_dir)
        self._started = False

    def _atomic_write(self, target: Path, content: str) -> None:
        temp_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.tool_results_dir,
                prefix=".tmp-",
                delete=False,
            ) as handle:
                temp_name = handle.name
                os.chmod(temp_name, 0o600)
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, target)
            temp_name = None
            os.chmod(target, 0o600)
        finally:
            if temp_name is not None:
                try:
                    Path(temp_name).unlink()
                except FileNotFoundError:
                    pass

    def _write_session_marker(self) -> None:
        marker = {
            "pid": os.getpid(),
            "created_at": time.time(),
            "session_id": self.session_id,
        }
        target = self.session_dir / "session.json"
        self._atomic_write_json(target, marker)

    def _atomic_write_json(self, target: Path, payload: dict[str, object]) -> None:
        text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        temp_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=target.parent,
                prefix=".session-",
                delete=False,
            ) as handle:
                temp_name = handle.name
                os.chmod(temp_name, 0o600)
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, target)
            temp_name = None
            os.chmod(target, 0o600)
        finally:
            if temp_name is not None:
                try:
                    Path(temp_name).unlink()
                except FileNotFoundError:
                    pass

    def _cleanup_stale_sessions(self) -> None:
        for candidate in self.context_root.iterdir():
            if not candidate.is_dir() or candidate.is_symlink():
                continue
            marker = candidate / "session.json"
            try:
                payload = json.loads(marker.read_text(encoding="utf-8"))
                pid = payload.get("pid")
            except (OSError, ValueError, AttributeError):
                continue
            if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
                continue
            if not _process_is_alive(pid):
                self._remove_session_dir(candidate)

    def _remove_session_dir(self, candidate: Path) -> None:
        if candidate.is_symlink():
            return
        try:
            root = self.context_root.resolve(strict=True)
            resolved = candidate.resolve(strict=True)
        except OSError:
            return
        if resolved.parent != root:
            return
        shutil.rmtree(resolved)


def is_persisted_output(content: object) -> bool:
    return isinstance(content, str) and content.startswith(PERSISTED_OUTPUT_START) and content.endswith(PERSISTED_OUTPUT_END)


def _new_session_id() -> str:
    return f"{int(time.time())}-{os.getpid()}-{uuid.uuid4().hex[:12]}"


def _safe_component(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip(".-")
    return (cleaned or "item")[:64]


def _process_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _preview(content: str) -> str:
    data = content.encode("utf-8")
    if len(data) <= PREVIEW_PART_BYTES * 2:
        return f"preview-head:\n{content}\n\npreview-tail:\n"
    head = _decode_prefix(data, PREVIEW_PART_BYTES)
    tail = _decode_suffix(data, PREVIEW_PART_BYTES)
    return f"preview-head:\n{head}\n\npreview-tail:\n{tail}"


def _decode_prefix(data: bytes, limit: int) -> str:
    return data[:limit].decode("utf-8", errors="ignore")


def _decode_suffix(data: bytes, limit: int) -> str:
    return data[-limit:].decode("utf-8", errors="ignore")


def _build_marker(
    *,
    tool_name: str,
    status: str,
    error_code: str | None,
    original_bytes: int,
    estimated_tokens: int,
    relative_path: str,
    preview: str,
) -> str:
    error_line = f"\nerror-code: {error_code}" if error_code else ""
    return (
        f"{PERSISTED_OUTPUT_START}\n"
        f"tool: {tool_name}\n"
        f"status: {status}{error_line}\n"
        f"original-bytes: {original_bytes}\n"
        f"estimated-tokens: {estimated_tokens}\n"
        f"path: {relative_path}\n\n"
        f"{preview}\n\n"
        "需要准确细节时必须按行范围重新读取 path，不得猜测省略内容。\n"
        f"{PERSISTED_OUTPUT_END}"
    )
