from __future__ import annotations

from pathlib import Path

import pytest

from artcode.evaluation.redaction import Redactor
from artcode.evaluation.workspace import (
    WorkspaceSafetyError,
    copy_fixture,
    diff_snapshots,
    resolve_workspace_path,
    snapshot_workspace,
)


def test_redactor_removes_explicit_and_common_secrets() -> None:
    raw = (
        "sk-known Authorization: Bearer bearer-123 api_key=key-123 token=tok-123 "
        "secret=sec-123 password=pwd-123"
    )
    safe = Redactor(["sk-known"]).redact(raw)
    for secret in (
        "sk-known",
        "bearer-123",
        "key-123",
        "tok-123",
        "sec-123",
        "pwd-123",
    ):
        assert secret not in safe


def test_preview_is_bounded_and_fingerprinted() -> None:
    preview = Redactor().preview("a" * 100, limit=10)
    assert preview.text == "a" * 10 + "…<truncated>"
    assert preview.original_chars == 100
    assert len(preview.sha256) == 64


def test_copy_and_diff_do_not_mutate_fixture(tmp_path: Path) -> None:
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "a.txt").write_text("before", encoding="utf-8")
    original = snapshot_workspace(fixture)
    workspace = tmp_path / "workspace"
    copy_fixture(fixture, workspace)
    (workspace / "a.txt").write_text("after", encoding="utf-8")
    (workspace / "b.txt").write_text("new", encoding="utf-8")
    changes = diff_snapshots(original, snapshot_workspace(workspace))
    assert [(item.path, item.kind) for item in changes] == [
        ("a.txt", "modified"),
        ("b.txt", "created"),
    ]
    assert snapshot_workspace(fixture) == original


def test_snapshot_can_exclude_artcode_internal_files(tmp_path: Path) -> None:
    (tmp_path / ".artcode").mkdir()
    (tmp_path / ".artcode" / "session.jsonl").write_text("secret")
    (tmp_path / "result.txt").write_text("ok")
    snapshot = snapshot_workspace(tmp_path, excluded_roots=(".artcode",))
    assert set(snapshot) == {"result.txt"}


def test_resolve_workspace_path_rejects_escape(tmp_path: Path) -> None:
    with pytest.raises(WorkspaceSafetyError):
        resolve_workspace_path(tmp_path, "../outside")
