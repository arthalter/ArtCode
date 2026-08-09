from __future__ import annotations

import os
import stat
import yaml
import pytest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from artcode.persistence import (
    MAX_INDEX_BYTES,
    MAX_INDEX_LINES,
    MAX_NOTE_BYTES,
    MemoryCategory,
    MemoryNote,
    MemoryNoteError,
    MemoryNoteStore,
    MemoryOperation,
    MemoryScope,
    MemoryStatus,
    parse_note,
    render_note,
)


NOW = datetime(2026, 8, 6, 8, 30, tzinfo=timezone.utc)


def _operation(
    action: str = "create",
    *,
    scope: MemoryScope = MemoryScope.PROJECT,
    category: MemoryCategory = MemoryCategory.PROJECT_KNOWLEDGE,
    target_id: str | None = None,
    summary: str = "稳定摘要",
    body: str = "可审计正文",
) -> MemoryOperation:
    return MemoryOperation(
        action=action,
        scope=scope,
        category=category,
        target_id=target_id,
        title="测试笔记",
        summary=summary,
        body=body,
        source_entry_ids=("msg-00000002",),
    )


def test_note_store_writes_readable_private_markdown_and_index(tmp_path: Path) -> None:
    store = MemoryNoteStore(tmp_path, MemoryScope.PROJECT)

    report = store.apply([_operation()], NOW, source_session="20260806-163000-a1b2")

    assert report.created == 1
    note_path = next(tmp_path.glob("mem-*.md"))
    note = parse_note(note_path)
    assert note.scope is MemoryScope.PROJECT
    assert note.category is MemoryCategory.PROJECT_KNOWLEDGE
    assert note.status is MemoryStatus.ACTIVE
    assert note.source_session == "20260806-163000-a1b2"
    assert stat.S_IMODE(note_path.stat().st_mode) == 0o600
    text = note_path.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    assert "# 测试笔记" in text
    assert note.id in store.read_index()


def test_user_scope_only_accepts_cross_project_preference(tmp_path: Path) -> None:
    store = MemoryNoteStore(tmp_path, MemoryScope.USER)
    operations = [
        _operation(scope=MemoryScope.USER, category=MemoryCategory.PREFERENCE),
        _operation(scope=MemoryScope.USER, category=MemoryCategory.CORRECTION),
        _operation(scope=MemoryScope.PROJECT, category=MemoryCategory.PREFERENCE),
    ]

    report = store.apply(operations, NOW)

    assert report.created == 1
    assert report.rejected == 2
    assert len(store.scan().notes) == 1


def test_update_and_supersede_preserve_auditable_file(tmp_path: Path) -> None:
    store = MemoryNoteStore(tmp_path, MemoryScope.PROJECT)
    store.apply([_operation()], NOW)
    original = store.scan().notes[0]

    update = _operation("update", target_id=original.id, body="更新后的正文")
    result = store.apply([update], NOW + timedelta(minutes=1))
    supersede = _operation("supersede", target_id=original.id)
    result2 = store.apply([supersede], NOW + timedelta(minutes=2))

    note = store.scan().notes[0]
    assert result.updated == 1
    assert result2.superseded == 1
    assert note.status is MemoryStatus.SUPERSEDED
    assert note.body == "更新后的正文"
    assert (tmp_path / f"{note.id}.md").exists()
    assert note.id not in store.read_index()


def test_invalid_or_oversized_operation_does_not_replace_existing_note(tmp_path: Path) -> None:
    store = MemoryNoteStore(tmp_path, MemoryScope.PROJECT)
    store.apply([_operation()], NOW)
    note = store.scan().notes[0]
    before = (tmp_path / f"{note.id}.md").read_bytes()

    report = store.apply(
        [_operation("update", target_id=note.id, summary="x" * 121, body="y" * 9000)],
        NOW + timedelta(minutes=1),
    )

    assert report.rejected == 1
    assert (tmp_path / f"{note.id}.md").read_bytes() == before


def test_scan_skips_bad_note_and_rebuilds_missing_or_bad_index(tmp_path: Path) -> None:
    store = MemoryNoteStore(tmp_path, MemoryScope.PROJECT)
    store.apply([_operation()], NOW)
    (tmp_path / "mem-20260806-000000-dead.md").write_text("bad", encoding="utf-8")
    store.index_path.write_bytes(b"\xff")

    index = store.read_index()
    scan = store.scan()

    assert len(scan.notes) == 1
    assert len(scan.issues) == 1
    assert scan.notes[0].id in index


def test_index_order_summary_and_dual_budget_are_deterministic(tmp_path: Path) -> None:
    order_store = MemoryNoteStore(tmp_path / "order", MemoryScope.PROJECT)
    for index, category in enumerate(
        (
            MemoryCategory.REFERENCE,
            MemoryCategory.PROJECT_KNOWLEDGE,
            MemoryCategory.CORRECTION,
            MemoryCategory.PREFERENCE,
        )
    ):
        order_store.apply([_operation(category=category)], NOW + timedelta(seconds=index))
    ordered = order_store.read_index()
    assert ordered.index("## 用户偏好") < ordered.index("## 纠正反馈")
    assert ordered.index("## 纠正反馈") < ordered.index("## 项目知识")
    assert ordered.index("## 项目知识") < ordered.index("## 参考资料")

    store = MemoryNoteStore(tmp_path, MemoryScope.PROJECT)
    categories = [
        MemoryCategory.REFERENCE,
        MemoryCategory.PROJECT_KNOWLEDGE,
        MemoryCategory.CORRECTION,
        MemoryCategory.PREFERENCE,
    ]
    operations = [
        _operation(category=categories[index % 4], summary=("中🙂" * 60)[:120])
        for index in range(230)
    ]
    store.apply(operations, NOW)
    first = store.read_index()
    report = store.rebuild_index()
    second = store.read_index()

    assert first == second
    assert report.line_count <= MAX_INDEX_LINES
    assert report.byte_count <= MAX_INDEX_BYTES
    assert report.omitted_count > 0
    assert "未索引" in first


def test_apply_handles_noop_invalid_actions_and_targets(tmp_path: Path) -> None:
    store = MemoryNoteStore(tmp_path, MemoryScope.PROJECT)
    report = store.apply(
        [
            _operation("noop"),
            _operation("create", target_id="mem-20260806-000000-dead"),
            _operation("update", target_id="mem-20260806-000000-dead"),
            _operation("unknown"),
        ],
        NOW,
    )
    assert report.created == 0
    assert report.rejected == 3
    assert report.status == "rejected"


def test_scan_rejects_symlink_and_wrong_scope(tmp_path: Path) -> None:
    store = MemoryNoteStore(tmp_path, MemoryScope.PROJECT)
    user_store = MemoryNoteStore(tmp_path / "user", MemoryScope.USER)
    user_store.apply(
        [_operation(scope=MemoryScope.USER, category=MemoryCategory.PREFERENCE)], NOW
    )
    user_note = next((tmp_path / "user").glob("mem-*.md"))
    wrong_scope = tmp_path / user_note.name
    wrong_scope.write_bytes(user_note.read_bytes())
    link = tmp_path / "mem-20260806-000000-dead.md"
    link.symlink_to(wrong_scope)
    scan = store.scan()
    assert scan.notes == ()
    assert len(scan.issues) == 2


def test_note_id_collision_exhaustion_is_reported(tmp_path: Path, monkeypatch) -> None:
    store = MemoryNoteStore(tmp_path, MemoryScope.PROJECT)
    monkeypatch.setattr("artcode.persistence.notes.secrets.token_hex", lambda _: "dead")
    name = NOW.astimezone().strftime("mem-%Y%m%d-%H%M%S") + "-dead.md"
    (tmp_path / name).write_text("occupied", encoding="utf-8")
    with pytest.raises(MemoryNoteError, match="无法生成"):
        store._new_note_id(NOW)


@pytest.mark.parametrize(
    "change",
    ["id", "scope", "category"],
)
def test_render_note_rejects_invalid_identity_fields(change: str) -> None:
    values = dict(
        id="mem-20260806-083000-dead",
        scope=MemoryScope.PROJECT,
        category=MemoryCategory.PROJECT_KNOWLEDGE,
        status=MemoryStatus.ACTIVE,
        title="title",
        summary="summary",
        body="body",
        created_at=NOW,
        updated_at=NOW,
        source_session="unknown",
        source_entry_ids=("msg-00000001",),
    )
    values[change] = "invalid"
    with pytest.raises(MemoryNoteError, match="字段非法"):
        render_note(MemoryNote(**values))


def _valid_note_parts() -> tuple[dict, str]:
    note = MemoryNote(
        id="mem-20260806-083000-dead",
        scope=MemoryScope.PROJECT,
        category=MemoryCategory.PROJECT_KNOWLEDGE,
        status=MemoryStatus.ACTIVE,
        title="title",
        summary="summary",
        body="body",
        created_at=NOW,
        updated_at=NOW,
        source_session="unknown",
        source_entry_ids=("msg-00000001",),
    )
    text = render_note(note)
    frontmatter, body = text[4:].split("\n---\n", 1)
    return yaml.safe_load(frontmatter), body


@pytest.mark.parametrize(
    ("scenario", "message"),
    [
        ("fields", "字段集合"),
        ("id", "ID 格式"),
        ("filename", "文件名"),
        ("summary", "摘要超过"),
        ("source-type", "source_entry_ids 必须"),
        ("source-format", "source_entry_ids 格式"),
        ("heading", "正文标题"),
        ("body", "正文不能为空"),
        ("enum", "作用域、类别或状态"),
        ("session", "source_session"),
        ("timezone", "UTC Z"),
        ("timestamp", "时间格式"),
        ("string", "title 必须"),
    ],
)
def test_parse_note_validation_matrix(tmp_path: Path, scenario: str, message: str) -> None:
    metadata, body = _valid_note_parts()
    filename = metadata["id"] + ".md"
    if scenario == "fields":
        metadata["extra"] = True
    elif scenario == "id":
        metadata["id"] = "bad"
    elif scenario == "filename":
        filename = "mem-20260806-083000-cafe.md"
    elif scenario == "summary":
        metadata["summary"] = "x" * 121
    elif scenario == "source-type":
        metadata["source_entry_ids"] = []
    elif scenario == "source-format":
        metadata["source_entry_ids"] = ["bad"]
    elif scenario == "heading":
        body = body.replace("# title", "# other")
    elif scenario == "body":
        body = "\n# title\n\n"
    elif scenario == "enum":
        metadata["scope"] = "invalid"
    elif scenario == "session":
        metadata["source_session"] = "invalid"
    elif scenario == "timezone":
        metadata["created_at"] = "2026-08-06T08:30:00+00:00"
    elif scenario == "timestamp":
        metadata["created_at"] = "not-a-dateZ"
    else:
        metadata["title"] = " "
    text = "---\n" + yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False).strip() + "\n---\n" + body
    path = tmp_path / filename
    path.write_text(text, encoding="utf-8")
    with pytest.raises(MemoryNoteError, match=message):
        parse_note(path)


@pytest.mark.parametrize("payload", [b"x" * (MAX_NOTE_BYTES + 1), b"plain text"])
def test_parse_note_rejects_size_and_missing_frontmatter(tmp_path: Path, payload: bytes) -> None:
    path = tmp_path / "mem-20260806-083000-dead.md"
    path.write_bytes(payload)
    with pytest.raises(MemoryNoteError):
        parse_note(path)


def test_commit_validation_rejects_missing_fields_and_oversized_render(tmp_path: Path) -> None:
    store = MemoryNoteStore(tmp_path, MemoryScope.PROJECT)
    base = _operation(summary="", body="")
    assert store.apply([base], NOW).rejected == 1
    assert store.apply([_operation(body="x" * MAX_NOTE_BYTES)], NOW).rejected == 1
