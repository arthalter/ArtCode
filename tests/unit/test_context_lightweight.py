from __future__ import annotations

from artcode.context_management import ContextArtifactStore, LightweightCompactor
from artcode.context_management.artifacts import is_persisted_output
from artcode.conversation import ConversationContext
from artcode.providers.tool_calls import ToolCall
from artcode.tools import success_result


def append_tool_group(context: ConversationContext, sizes: list[int]) -> None:
    calls = [ToolCall(f"call-{index}", "read_file", "{}") for index in range(len(sizes))]
    context.append_assistant_tool_call(calls)
    for call, size in zip(calls, sizes, strict=True):
        context.append_tool_result(call, success_result("read_file", "ok", "a" * size))


def tool_contents(context: ConversationContext) -> list[str]:
    return [
        message["content"]
        for message in context.export_messages()
        if message.get("role") == "tool"
    ]


def test_single_threshold_is_strictly_greater_than_8000(tmp_path) -> None:
    store = ContextArtifactStore(tmp_path, "session")
    store.start()
    context = ConversationContext("system")
    append_tool_group(context, [24_000, 24_003])

    report = LightweightCompactor(store).apply(context)

    contents = tool_contents(context)
    assert not is_persisted_output(contents[0])
    assert is_persisted_output(contents[1])
    assert report.persisted_count == 1
    store.close()


def test_aggregate_persists_largest_until_group_is_within_limit(tmp_path) -> None:
    store = ContextArtifactStore(tmp_path, "session")
    store.start()
    context = ConversationContext("system")
    append_tool_group(context, [24_000, 21_000, 12_003])

    report = LightweightCompactor(store).apply(context)

    contents = tool_contents(context)
    assert is_persisted_output(contents[0])
    assert not is_persisted_output(contents[1])
    assert not is_persisted_output(contents[2])
    assert report.persisted_count == 1
    store.close()


def test_equal_sizes_use_message_order(tmp_path) -> None:
    store = ContextArtifactStore(tmp_path, "session")
    store.start()
    context = ConversationContext("system")
    append_tool_group(context, [18_000, 18_000, 18_000])

    LightweightCompactor(store).apply(context)

    contents = tool_contents(context)
    assert is_persisted_output(contents[0])
    assert not is_persisted_output(contents[1])
    assert not is_persisted_output(contents[2])
    store.close()


def test_repeated_apply_is_idempotent(tmp_path) -> None:
    store = ContextArtifactStore(tmp_path, "session")
    store.start()
    context = ConversationContext("system")
    append_tool_group(context, [30_000])
    compactor = LightweightCompactor(store)

    first = compactor.apply(context)
    files_after_first = list(store.tool_results_dir.iterdir())
    second = compactor.apply(context)

    assert first.persisted_count == 1
    assert second.persisted_count == 0
    assert list(store.tool_results_dir.iterdir()) == files_after_first
    store.close()


def test_persistence_failure_keeps_full_result_and_marks_protected(tmp_path, monkeypatch) -> None:
    store = ContextArtifactStore(tmp_path, "session")
    store.start()
    context = ConversationContext("system")
    append_tool_group(context, [30_000])
    monkeypatch.setattr(store, "persist", lambda entry: (_ for _ in ()).throw(OSError("disk full")))

    report = LightweightCompactor(store).apply(context)

    assert report.persisted_count == 0
    assert len(report.failures) == 1
    assert "a" * 30_000 in tool_contents(context)[0]
    assert context.snapshot().entries[-1].persistence_failed is True
    store.close()
