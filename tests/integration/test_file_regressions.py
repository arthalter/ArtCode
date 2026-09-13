from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess

from artcode._tool import LocalTools
from artcode._workspace import LocalWorkspace
from artcode.core.tool import PermissionMode, RunMode, ToolCall


async def test_edited_script_can_still_be_executed_directly(tmp_path: Path) -> None:
    script = tmp_path / "hello.sh"
    script.write_text("#!/bin/sh\nprintf before\n", encoding="utf-8")
    script.chmod(0o755)
    workspace = LocalWorkspace(tmp_path)
    tools = LocalTools(permission_mode=PermissionMode.EDIT)
    results = await tools.execute_batch(
        tools.open_run(workspace, RunMode.ACT),
        (ToolCall("edit", "edit_file", json.dumps({
            "path": "hello.sh", "old_text": "before", "new_text": "after"
        })),),
    )

    assert results[0].ok is True
    execution = subprocess.run([str(script)], capture_output=True, text=True, check=True)
    assert execution.stdout == "after"


async def test_read_file_continuation_recovers_every_line_without_repeating(tmp_path: Path) -> None:
    content = "alpha\nbravo-value\n中文字符\ntail"
    (tmp_path / "notes.txt").write_text(content, encoding="utf-8")
    workspace = LocalWorkspace(tmp_path, read_char_limit=13)
    tools = LocalTools()
    run = tools.open_run(workspace, RunMode.CHAT)
    start_line = 1
    chunks: list[str] = []

    for index in range(4):
        result, = await tools.execute_batch(
            run,
            (ToolCall(str(index), "read_file", json.dumps({
                "path": "notes.txt", "start_line": start_line
            })),),
        )
        assert result.ok is True
        continuation = re.search(r"\n\[内容已截断；next_line=(\d+)\]$", result.content)
        if continuation is None:
            chunks.append(result.content)
            break
        chunks.append(result.content[:continuation.start()])
        next_line = int(continuation.group(1))
        assert next_line > start_line
        start_line = next_line

    assert "".join(chunks) == content


async def test_read_file_returns_success_for_empty_python_package(tmp_path: Path) -> None:
    (tmp_path / "__init__.py").touch()
    workspace = LocalWorkspace(tmp_path)
    tools = LocalTools()

    result, = await tools.execute_batch(
        tools.open_run(workspace, RunMode.CHAT),
        (ToolCall("read", "read_file", '{"path":"__init__.py"}'),),
    )

    assert result.ok is True
    assert result.content == ""
