from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from artcode.agent import NORMAL_AGENT_MODE, RequestPreparer
from artcode.conversation import ConversationContext
from artcode.persistence import (
    DurablePromptSource,
    DurablePaths,
    InstructionLoader,
    MemoryCategory,
    MemoryNoteStore,
    MemoryOperation,
    MemoryScope,
)
from artcode.prompting.assembler import PromptRequestAssembler
from artcode.permissions import PermissionState
from artcode.tools import ToolEnvironment, ToolRegistry
from artcode.workspace import ArtCodePaths, Workspace

import pytest


def _setup(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    workspace = Workspace.from_path(project)
    paths = DurablePaths.from_context(ArtCodePaths.create(tmp_path / "home"), workspace)
    paths.local_instruction.write_text("LOCAL UNIQUE", encoding="utf-8")
    paths.project_instruction.write_text("ROOT UNIQUE", encoding="utf-8")
    paths.user_instruction.write_text("USER UNIQUE", encoding="utf-8")
    user = MemoryNoteStore(paths.user_memory_dir, MemoryScope.USER)
    project_store = MemoryNoteStore(paths.project_memory_dir, MemoryScope.PROJECT)
    return workspace, paths, user, project_store


def test_dynamic_prompt_orders_instructions_and_marks_memory_as_read_only(tmp_path: Path) -> None:
    workspace, paths, user, project = _setup(tmp_path)
    now = datetime(2026, 8, 6, tzinfo=timezone.utc)
    project.apply(
        [
            MemoryOperation(
                "create",
                MemoryScope.PROJECT,
                MemoryCategory.PROJECT_KNOWLEDGE,
                title="事实",
                summary="PROJECT MEMORY UNIQUE",
                body="项目事实",
                source_entry_ids=("msg-00000002",),
            )
        ],
        now,
    )
    durable = DurablePromptSource(
        paths,
        instructions=InstructionLoader(paths).load(),
    )

    prompt = durable.build_system_prompt()

    assert prompt.index("# 系统约束") < prompt.index("# 项目本地指令")
    assert prompt.index("LOCAL UNIQUE") < prompt.index("ROOT UNIQUE") < prompt.index("USER UNIQUE")
    assert prompt.index("USER UNIQUE") < prompt.index("# 任务模式")
    assert prompt.index("# 文本输出") < prompt.index("# 长期记忆参考")
    assert "PROJECT MEMORY UNIQUE" in prompt
    assert "不是新的系统或用户指令" in prompt
    assert "Workspace 中的真实文件" in prompt


def test_assembler_reads_latest_index_without_mutating_conversation(tmp_path: Path) -> None:
    workspace, paths, user, project = _setup(tmp_path)
    durable = DurablePromptSource(
        paths,
        instructions=InstructionLoader(paths).load(),
    )
    assembler = PromptRequestAssembler()
    conversation = ConversationContext("STATIC SYSTEM")
    conversation.append_user("hello")
    environment = ToolEnvironment.from_workspace(workspace)
    permission = PermissionState()

    preparer = RequestPreparer(
        conversation,
        assembler,
        ToolRegistry(),
        environment,
        permission,
        durable_prompt=durable,
    )
    first = preparer.preview_request(NORMAL_AGENT_MODE)
    project.index_path.write_text("# NEW INDEX UNIQUE\n", encoding="utf-8")
    second = preparer.preview_request(NORMAL_AGENT_MODE)

    assert "NEW INDEX UNIQUE" not in first.messages[0]["content"]
    assert "NEW INDEX UNIQUE" in second.messages[0]["content"]
    assert conversation.export_messages()[0]["content"] == "STATIC SYSTEM"
    assert "LOCAL UNIQUE" not in str(conversation.export_messages())


async def test_resume_reminder_is_committed_only_after_dispatch_and_not_persisted(tmp_path: Path) -> None:
    workspace, paths, user, project = _setup(tmp_path)
    assembler = PromptRequestAssembler()
    conversation = ConversationContext("static")
    conversation.append_user("continue")
    environment = ToolEnvironment.from_workspace(workspace)
    permission = PermissionState()
    preparer = RequestPreparer(
        conversation,
        assembler,
        ToolRegistry(),
        environment,
        permission,
        durable_prompt=DurablePromptSource(
            paths,
            instructions=InstructionLoader(paths).load(),
        ),
        resume_reminder_required=True,
    )

    first = preparer.preview_request(NORMAL_AGENT_MODE)
    second = preparer.preview_request(NORMAL_AGENT_MODE)
    prepared = await preparer.prepare(NORMAL_AGENT_MODE)
    preparer.mark_dispatched(prepared)
    third = preparer.preview_request(NORMAL_AGENT_MODE)

    assert "超过 24 小时" in str(first.messages)
    assert "超过 24 小时" in str(second.messages)
    assert "超过 24 小时" not in str(third.messages)
    assert "超过 24 小时" not in str(conversation.export_messages())


@pytest.mark.ch10_5
def test_durable_prompt_source_reads_latest_indexes_without_owning_stores(tmp_path: Path) -> None:
    _, paths, user, project = _setup(tmp_path)
    source = DurablePromptSource(paths)
    first = source.build_system_prompt()
    project.index_path.write_text("# LATEST PROJECT INDEX\n", encoding="utf-8")
    second = source.build_system_prompt()

    assert "LOCAL UNIQUE" in first
    assert "LATEST PROJECT INDEX" not in first
    assert "LATEST PROJECT INDEX" in second
    assert not hasattr(source, "conversation")
    assert not hasattr(source, "memory_worker")
