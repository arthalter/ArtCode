from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path


def _event_payload(event) -> dict:
    event_type = getattr(getattr(event, "type", None), "value", str(getattr(event, "type", "")))
    payload = getattr(event, "payload", {})
    result = {"type": event_type}
    if not isinstance(payload, dict):
        return result
    for key, value in payload.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            result[str(key)] = value
        elif key == "result":
            result["result"] = {
                name: getattr(value, name, None)
                for name in ("tool_name", "ok", "status", "error_code", "message")
            }
        elif key == "tool_call":
            result["tool_call"] = {
                name: getattr(value, name, None)
                for name in ("id", "name", "arguments_json")
            }
    return result


async def _run(source: Path, workspace: Path, payload: dict) -> tuple[list[dict], list[dict]]:
    sys.path.insert(0, str(source))
    from artcode.agent import AgentLoop, AgentRunRequest, NORMAL_AGENT_MODE
    from artcode.config import parse_config
    from artcode.conversation import ConversationContext
    from artcode.permissions import PermissionMode, PermissionState, ShellPolicy
    from artcode.tools import (
        AllowedPathPolicy,
        ToolExecutionContext,
        create_default_tool_registry,
    )

    modern = (source / "artcode" / "agent" / "request.py").is_file()
    thinking = {"enabled": False} if modern else {"enabled": False, "effort": "high"}
    config = parse_config(
        {
            "protocol": "openai",
            "model": os.environ["ARTCODE_EVAL_MODEL"],
            "base_url": os.environ["ARTCODE_EVAL_BASE_URL"],
            "api_key": os.environ["ARTCODE_EVAL_API_KEY"],
            "thinking": thinking,
            "context": {"window_tokens": int(payload["context_window_tokens"])},
        }
    )
    if modern:
        from artcode.providers import DeepSeekChatProvider

        provider = DeepSeekChatProvider(config)
    else:
        from artcode.providers import OpenAICompatibleProvider

        provider = OpenAICompatibleProvider(config)

    state = PermissionState(
        mode=PermissionMode.FULL,
        shell_policy=ShellPolicy.UNSANDBOXED_ASK,
    )
    registry = create_default_tool_registry()
    context = ToolExecutionContext(
        AllowedPathPolicy((workspace,)),
        command_timeout_seconds=float(payload["command_timeout_seconds"]),
        default_cwd=workspace,
        shell_policy=ShellPolicy.UNSANDBOXED_ASK,
        permission_state=state,
    )
    conversation = ConversationContext()
    loop = AgentLoop(provider, conversation, registry, context)
    events = []
    try:
        async for event in loop.run(
            AgentRunRequest(
                payload["prompt"],
                NORMAL_AGENT_MODE,
                max_iterations=int(payload["max_iterations"]),
                final_summary_on_abnormal_stop=False,
            )
        ):
            events.append(_event_payload(event))
    finally:
        close = getattr(provider, "close", None)
        if callable(close):
            await close()
    return events, conversation.export_messages()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--artcode-home", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    os.environ["HOME"] = str(args.artcode_home.resolve())
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    repository = (args.workspace / payload["repository_dir"]).resolve(strict=True)
    if args.workspace.resolve() not in repository.parents:
        raise ValueError("任务仓库必须位于隔离 Workspace 内")
    events, messages = asyncio.run(_run(args.source, repository, payload))
    patch = subprocess.run(
        ["git", "-C", str(repository), "diff", "--binary", "--no-ext-diff"],
        text=True,
        capture_output=True,
        check=True,
    ).stdout
    patch_path = args.output.with_name("generated.patch")
    patch_path.write_text(patch, encoding="utf-8")
    args.output.write_text(
        json.dumps(
            {
                "status": "complete",
                "patch_path": str(patch_path),
                "patch_bytes": len(patch.encode("utf-8")),
                "events": events,
                "messages": messages,
            },
            ensure_ascii=False,
            default=str,
        ),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
