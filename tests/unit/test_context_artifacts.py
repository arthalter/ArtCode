from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from artcode.context_management.artifacts import ContextArtifactStore
from artcode.conversation import ConversationContext
from artcode.providers.tool_calls import ToolCall
from artcode.tools import success_result
from artcode.workspace import Workspace


def tool_entry(content: str, tool_call_id: str = "../../call/1"):
    context = ConversationContext("system")
    context.append_tool_result(
        ToolCall(tool_call_id, "read/file", "{}"),
        success_result("read/file", "ok", content),
    )
    return context.snapshot().entries[-1]


def test_persist_writes_complete_content_and_safe_marker(tmp_path: Path) -> None:
    workspace = Workspace.from_path(tmp_path)
    store = ContextArtifactStore(workspace, "session-a")
    store.start()
    content = "开头\n" + "中" * 3_000 + "\nUNIQUE_TAIL"

    persisted = store.persist(tool_entry(content))
    target = workspace.root / persisted.relative_path

    assert target.read_text(encoding="utf-8") == content
    assert target.parent == store.tool_results_dir
    assert ".." not in target.name
    assert persisted.marker.startswith("<persisted-output>")
    assert persisted.relative_path in persisted.marker
    assert "UNIQUE_TAIL" in persisted.preview
    assert target.stat().st_mode & 0o777 == 0o600
    store.close()


def test_atomic_failure_leaves_no_partial_file(tmp_path: Path, monkeypatch) -> None:
    store = ContextArtifactStore(tmp_path, "session-a")
    store.start()
    monkeypatch.setattr(os, "replace", lambda source, target: (_ for _ in ()).throw(OSError("boom")))

    with pytest.raises(OSError, match="boom"):
        store.persist(tool_entry("secret"))

    assert list(store.tool_results_dir.iterdir()) == []
    store.close()


def test_artifact_identity_rejects_prefix_and_symlink(tmp_path: Path) -> None:
    store = ContextArtifactStore(tmp_path, "session-a")
    store.start()
    persisted = store.persist(tool_entry("hello"))
    real = tmp_path / persisted.relative_path
    outside = tmp_path / ".artcode" / "context-other" / "fake.txt"
    outside.parent.mkdir()
    outside.write_text("outside", encoding="utf-8")
    link = store.tool_results_dir / "link.txt"
    link.symlink_to(outside)

    assert store.is_current_artifact(real)
    assert not store.is_current_artifact(outside)
    assert not store.is_current_artifact(link)
    store.close()


def test_start_cleans_dead_session_but_keeps_live_session(tmp_path: Path) -> None:
    root = tmp_path / ".artcode" / "context"
    dead = root / "dead"
    live = root / "live"
    dead.mkdir(parents=True)
    live.mkdir()
    (dead / "session.json").write_text(json.dumps({"pid": 99_999_999}), encoding="utf-8")
    (live / "session.json").write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")

    store = ContextArtifactStore(tmp_path, "current")
    store.start()

    assert not dead.exists()
    assert live.exists()
    store.close()
    assert live.exists()


def test_close_is_idempotent_and_only_removes_current_session(tmp_path: Path) -> None:
    store = ContextArtifactStore(tmp_path, "current")
    store.start()
    other = store.context_root / "other"
    other.mkdir()

    store.close()
    store.close()

    assert not store.session_dir.exists()
    assert other.exists()


def test_store_rejects_unsafe_session_id_and_context_symlink(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="会话 ID"):
        ContextArtifactStore(tmp_path, "../../outside")

    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / ".artcode").symlink_to(outside, target_is_directory=True)
    store = ContextArtifactStore(tmp_path, "safe")
    with pytest.raises(RuntimeError, match="符号链接"):
        store.start()
