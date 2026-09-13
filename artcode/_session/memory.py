from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import tempfile

from artcode.core.model import Completed, Model, ModelMessage, ModelRequest, TextDelta, ToolRequests
from artcode.core.session import MemoryReport, RunLease


class MemoryManager:
    def __init__(self, user_path: Path, project_path: Path) -> None:
        self.user_path = user_path
        self.project_path = project_path
        self.user_index = user_path.with_name("memory.index.md")
        self.project_index = project_path.with_name("memory.index.md")
        self._lock = asyncio.Lock()
        self._tasks: set[asyncio.Task[None]] = set()
        self.last_report: MemoryReport | None = None
        _rebuild_index(self.user_path, self.user_index, "ArtCode 用户偏好索引")
        _rebuild_index(self.project_path, self.project_index, "ArtCode 项目事实索引")

    @property
    def pending(self) -> int:
        return sum(not task.done() for task in self._tasks)

    def schedule(self, lease: RunLease, assistant_text: str, model: Model) -> None:
        task = asyncio.create_task(
            self._update(lease.goal, assistant_text, model),
            name=f"memory:{lease.id}",
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def wait_idle(self) -> None:
        while self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)

    def cancel(self) -> None:
        for task in tuple(self._tasks):
            task.cancel()

    async def _update(self, goal: str, assistant_text: str, model: Model) -> None:
        async with self._lock:
            try:
                request = ModelRequest(
                    (
                        ModelMessage(
                            "system",
                            "Extract durable memory as strict JSON with exactly user_preferences and "
                            "project_facts string arrays. Do not call tools. Store only stable facts.",
                        ),
                        ModelMessage(
                            "user",
                            json.dumps(
                                {"goal": goal, "assistant": assistant_text},
                                ensure_ascii=False,
                            ),
                        ),
                    ),
                    max_output_tokens=2_000,
                    thinking_enabled=False,
                )
                parts: list[str] = []
                completed = False
                async for event in model.stream(request):
                    if isinstance(event, TextDelta):
                        parts.append(event.text)
                    elif isinstance(event, ToolRequests):
                        raise ValueError("记忆更新不得调用 Tool。")
                    elif isinstance(event, Completed):
                        completed = True
                if not completed:
                    raise ValueError("记忆更新响应未完成。")
                payload = json.loads("".join(parts))
                preferences, facts = _validate(payload)
                added_user = _append_unique(self.user_path, preferences, "ArtCode 用户偏好")
                added_project = _append_unique(self.project_path, facts, "ArtCode 项目事实")
                _rebuild_index(self.user_path, self.user_index, "ArtCode 用户偏好索引")
                _rebuild_index(self.project_path, self.project_index, "ArtCode 项目事实索引")
                self.last_report = MemoryReport("success", added_user, added_project)
            except asyncio.CancelledError:
                raise
            except BaseException as exc:
                self.last_report = MemoryReport("failed", detail=str(exc))


def _validate(payload: object) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if not isinstance(payload, dict) or set(payload) != {"user_preferences", "project_facts"}:
        raise ValueError("记忆更新 JSON 字段无效。")
    values: list[tuple[str, ...]] = []
    for key in ("user_preferences", "project_facts"):
        raw = payload[key]
        if not isinstance(raw, list) or any(not isinstance(item, str) or not item.strip() for item in raw):
            raise ValueError(f"记忆更新 {key} 必须是非空字符串列表。")
        values.append(tuple(dict.fromkeys(item.strip() for item in raw)))
    return values[0], values[1]


def _append_unique(path: Path, values: tuple[str, ...], title: str) -> int:
    if not values:
        return 0
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError("记忆路径不能是符号链接。")
    try:
        existing = path.read_text(encoding="utf-8") if path.is_file() else f"# {title}\n\n"
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError(f"无法读取记忆：{exc}") from exc
    existing_values = {
        line.removeprefix("- ").strip()
        for line in existing.splitlines()
        if line.startswith("- ")
    }
    additions = tuple(value for value in values if value not in existing_values)
    if not additions:
        return 0
    content = existing.rstrip() + "\n" + "".join(f"- {value}\n" for value in additions)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, prefix=".memory-", delete=False
        ) as handle:
            temporary = handle.name
            os.chmod(temporary, 0o600)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
        os.chmod(path, 0o600)
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)
    return len(additions)


def _rebuild_index(source: Path, index: Path, title: str) -> None:
    if not source.is_file() or source.is_symlink():
        return
    try:
        lines = [line for line in source.read_text(encoding="utf-8").splitlines() if line.startswith("- ")]
    except (OSError, UnicodeDecodeError):
        return
    content = f"# {title}\n\n> 此文件可重建；真实来源是 {source.name}。\n\n" + "\n".join(lines) + ("\n" if lines else "")
    if index.is_symlink() or index.parent.is_symlink():
        return
    index.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=index.parent, prefix=".memory-index-", delete=False
        ) as handle:
            temporary = handle.name
            os.chmod(temporary, 0o600)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, index)
        temporary = None
        os.chmod(index, 0o600)
    except OSError:
        pass
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)
