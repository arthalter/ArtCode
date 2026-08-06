from __future__ import annotations

import os
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path

from artcode.persistence import (
    MAX_INDEX_BYTES,
    MAX_INDEX_LINES,
    MemoryCategory,
    MemoryNoteStore,
    MemoryOperation,
    MemoryScope,
    MemoryStatus,
    parse_note,
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
