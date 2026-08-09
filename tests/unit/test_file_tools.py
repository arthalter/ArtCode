from __future__ import annotations

from artcode.agent import NORMAL_AGENT_MODE
from artcode.permissions import PermissionState
from artcode.tools.base import PreparedToolCall, ToolEnvironment, ToolRunContext
from artcode.tools.file_tools import EditFileTool, FindFilesTool, ReadFileTool, SearchTextTool, WriteFileTool
from artcode.context_management import ContextArtifactStore
from artcode.conversation import ConversationContext
from artcode.providers.tool_calls import ToolCall
from artcode.tools import success_result


def context_for(root, *, artifact_store=None) -> ToolRunContext:
    root.mkdir(exist_ok=True)
    return ToolRunContext(
        ToolEnvironment.from_workspace(root, artifact_store=artifact_store),
        NORMAL_AGENT_MODE,
        PermissionState().snapshot(),
    )


async def run_prepared(tool, arguments, context: ToolRunContext):
    prepared = tool.prepare(arguments, context)
    assert isinstance(prepared, PreparedToolCall)
    return await tool.execute(prepared, context)


async def test_read_file_reads_utf8_text(tmp_path) -> None:
    context = context_for(tmp_path / "sandbox")
    (context.default_cwd / "note.txt").write_text("hello", encoding="utf-8")

    result = await run_prepared(ReadFileTool(), {"path": "note.txt"}, context)

    assert result.ok is True
    assert result.content == "hello"


async def test_read_file_supports_line_range(tmp_path) -> None:
    context = context_for(tmp_path / "sandbox")
    (context.default_cwd / "note.txt").write_text("a\nb\nc\n", encoding="utf-8")

    result = await run_prepared(ReadFileTool(), {"path": "note.txt", "start_line": 2, "end_line": 2}, context)

    assert result.content == "b\n"


async def test_read_file_decode_error(tmp_path) -> None:
    context = context_for(tmp_path / "sandbox")
    (context.default_cwd / "bin.dat").write_bytes(b"\xff\xfe")

    result = await run_prepared(ReadFileTool(), {"path": "bin.dat"}, context)

    assert result.ok is False
    assert result.error_code == "decode_error"


async def test_read_file_outside_allowed_dir_is_rejected(tmp_path) -> None:
    context = context_for(tmp_path / "sandbox")
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")

    result = ReadFileTool().prepare({"path": str(outside)}, context)

    assert result.ok is False
    assert result.error_code == "path_outside_workspace"


async def test_read_file_keeps_large_result_complete(tmp_path) -> None:
    context = context_for(tmp_path / "sandbox")
    content = "a" * 25_000 + "UNIQUE_TAIL"
    (context.default_cwd / "note.txt").write_text(content, encoding="utf-8")

    result = await run_prepared(ReadFileTool(), {"path": "note.txt"}, context)

    assert result.content == content
    assert result.content.endswith("UNIQUE_TAIL")


async def test_current_artifact_requires_two_sided_line_range(tmp_path) -> None:
    root = tmp_path / "sandbox"
    root.mkdir()
    store = ContextArtifactStore(root, "session")
    store.start()
    context = context_for(root, artifact_store=store)
    conversation = ConversationContext("system")
    call = ToolCall("call-1", "read_file", "{}")
    conversation.append_tool_result(call, success_result("read_file", "ok", "one\ntwo\nthree\n"))
    persisted = store.persist(conversation.snapshot().entries[-1])

    missing_end = ReadFileTool().prepare(
        {"path": persisted.relative_path, "start_line": 1},
        context,
    )
    result = await run_prepared(
        ReadFileTool(),
        {"path": persisted.relative_path, "start_line": 2, "end_line": 2},
        context,
    )

    assert missing_end.error_code == "artifact_range_required"
    assert result.content == "two\n"
    store.close()


async def test_current_artifact_rejects_oversized_range(tmp_path) -> None:
    root = tmp_path / "sandbox"
    root.mkdir()
    store = ContextArtifactStore(root, "session")
    store.start()
    context = context_for(root, artifact_store=store)
    conversation = ConversationContext("system")
    call = ToolCall("call-1", "read_file", "{}")
    conversation.append_tool_result(call, success_result("read_file", "ok", "a" * 24_003 + "\n"))
    persisted = store.persist(conversation.snapshot().entries[-1])

    result = await run_prepared(
        ReadFileTool(),
        {"path": persisted.relative_path, "start_line": 1, "end_line": 1},
        context,
    )

    assert result.error_code == "artifact_range_too_large"
    store.close()


async def test_normal_file_still_accepts_one_sided_range(tmp_path) -> None:
    context = context_for(tmp_path / "sandbox")
    (context.default_cwd / "note.txt").write_text("one\ntwo\n", encoding="utf-8")

    result = await run_prepared(ReadFileTool(), {"path": "note.txt", "start_line": 2}, context)

    assert result.content == "two\n"


async def test_write_file_writes_new_file(tmp_path) -> None:
    context = context_for(tmp_path / "sandbox")

    result = await run_prepared(WriteFileTool(), {"path": "note.txt", "content": "hello"}, context)

    assert result.ok is True
    assert (context.default_cwd / "note.txt").read_text(encoding="utf-8") == "hello"


async def test_write_file_rejects_overwrite_without_flag(tmp_path) -> None:
    context = context_for(tmp_path / "sandbox")
    target = context.default_cwd / "note.txt"
    target.write_text("old", encoding="utf-8")

    result = WriteFileTool().prepare({"path": "note.txt", "content": "new"}, context)

    assert result.ok is False
    assert result.error_code == "already_exists"
    assert target.read_text(encoding="utf-8") == "old"


async def test_write_file_allows_explicit_overwrite(tmp_path) -> None:
    context = context_for(tmp_path / "sandbox")
    target = context.default_cwd / "note.txt"
    target.write_text("old", encoding="utf-8")

    result = await run_prepared(WriteFileTool(), {"path": "note.txt", "content": "new", "overwrite": True}, context)

    assert result.ok is True
    assert target.read_text(encoding="utf-8") == "new"


async def test_edit_file_replaces_unique_old_text(tmp_path) -> None:
    context = context_for(tmp_path / "sandbox")
    target = context.default_cwd / "note.txt"
    target.write_text("hello world", encoding="utf-8")

    result = await run_prepared(EditFileTool(), {"path": "note.txt", "old_text": "world", "new_text": "ArtCode"}, context)

    assert result.ok is True
    assert target.read_text(encoding="utf-8") == "hello ArtCode"


async def test_edit_file_rejects_missing_old_text(tmp_path) -> None:
    context = context_for(tmp_path / "sandbox")
    target = context.default_cwd / "note.txt"
    target.write_text("hello", encoding="utf-8")

    result = await run_prepared(EditFileTool(), {"path": "note.txt", "old_text": "missing", "new_text": "x"}, context)

    assert result.ok is False
    assert result.error_code == "old_text_not_found"
    assert target.read_text(encoding="utf-8") == "hello"


async def test_edit_file_rejects_non_unique_old_text(tmp_path) -> None:
    context = context_for(tmp_path / "sandbox")
    target = context.default_cwd / "note.txt"
    target.write_text("x x", encoding="utf-8")

    result = await run_prepared(EditFileTool(), {"path": "note.txt", "old_text": "x", "new_text": "y"}, context)

    assert result.ok is False
    assert result.error_code == "old_text_not_unique"
    assert target.read_text(encoding="utf-8") == "x x"


async def test_find_files_uses_glob_inside_allowed_dir(tmp_path) -> None:
    context = context_for(tmp_path / "sandbox")
    (context.default_cwd / "a.py").write_text("", encoding="utf-8")
    (context.default_cwd / "b.txt").write_text("", encoding="utf-8")

    result = await run_prepared(FindFilesTool(), {"pattern": "*.py"}, context)

    assert "a.py" in result.content
    assert "b.txt" not in result.content


async def test_find_files_filters_absolute_pattern_outside_allowed_dir(tmp_path) -> None:
    context = context_for(tmp_path / "sandbox")
    outside = tmp_path / "outside.py"
    outside.write_text("", encoding="utf-8")

    result = await run_prepared(FindFilesTool(), {"pattern": str(tmp_path / "*.py")}, context)

    assert str(outside) not in result.content


async def test_search_text_finds_plain_text_matches(tmp_path) -> None:
    context = context_for(tmp_path / "sandbox")
    (context.default_cwd / "a.txt").write_text("hello.*\nhello world\n", encoding="utf-8")

    result = await run_prepared(SearchTextTool(), {"query": "hello.*"}, context)

    assert '"line": 1' in result.content
    assert "hello world" not in result.content


async def test_search_text_skips_unreadable_files(tmp_path) -> None:
    context = context_for(tmp_path / "sandbox")
    (context.default_cwd / "a.txt").write_text("needle", encoding="utf-8")
    (context.default_cwd / "bin.dat").write_bytes(b"\xff\xfe")

    result = await run_prepared(SearchTextTool(), {"query": "needle"}, context)

    assert result.ok is True
    assert "needle" in result.content
    assert '"skipped_unreadable_files": 1' in result.content
