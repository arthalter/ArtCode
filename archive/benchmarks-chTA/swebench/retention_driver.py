from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _valid_summary(titles, placeholder: str) -> str:
    sections = [
        f"## {index}. {title}\n{placeholder if index == 6 else f'summary-{index}'}"
        for index, title in enumerate(titles, start=1)
    ]
    return "<analysis>deterministic</analysis><summary>" + "\n\n".join(sections) + "</summary>"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--artcode-home", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.source))

    from artcode.config import ContextConfig
    from artcode.context_management.manager import ContextManager
    from artcode.context_management.models import CompressionTrigger
    from artcode.context_management.retention import RetentionPlanner
    from artcode.context_management.summarizer import (
        ContextSummarizer,
        SUMMARY_TITLES,
        VERBATIM_PLACEHOLDER,
    )
    from artcode.conversation import ConversationContext

    payload = json.loads(args.input.read_text(encoding="utf-8"))
    prompt = payload["prompt"]
    expected = [item["expected"] for item in payload["probes"]]

    class Provider:
        async def stream_chat(self, messages, tools=None, *, options=None):
            from artcode.providers.events import content_delta_event, done_event

            yield content_delta_event(_valid_summary(SUMMARY_TITLES, VERBATIM_PLACEHOLDER))
            yield done_event()

        async def stream(self, request):
            from artcode.providers.events import ContentDelta, StreamCompleted

            yield ContentDelta(_valid_summary(SUMMARY_TITLES, VERBATIM_PLACEHOLDER))
            yield StreamCompleted()

    context = ConversationContext("system")
    context.append_user(prompt)
    for index in range(12):
        context.append_assistant(f"historical answer {index} " + "x" * 200)
        context.append_user(f"follow-up {index}")
    before = context.export_messages()
    if not all(any(value in str(item.get("content", "")) for item in before) for value in expected):
        args.output.write_text(json.dumps({"preflight": "missing"}), encoding="utf-8")
        return 3
    manager = ContextManager(
        ContextConfig(),
        ContextSummarizer(Provider(), context),
        retention_planner=RetentionPlanner(20, 3),
    )
    import asyncio

    report = asyncio.run(manager.compact(context, CompressionTrigger.MANUAL))
    result = {
        "preflight": "all_present",
        "compression_status": report.status,
        "messages": context.export_messages(),
    }
    args.output.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return 0 if report.status == "success" else 4


if __name__ == "__main__":
    raise SystemExit(main())
