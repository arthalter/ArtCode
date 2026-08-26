from __future__ import annotations


def handoff_payload(handoff: object | None) -> dict[str, object] | None:
    if handoff is None:
        return None
    names = (
        "baseline",
        "branch",
        "path",
        "retained",
        "tracked_changes",
        "staged_changes",
        "untracked_changes",
        "commits_ahead",
        "has_upstream",
        "all_commits_pushed",
        "message",
    )
    payload: dict[str, object] = {}
    for name in names:
        value = getattr(handoff, name, None)
        payload[name] = str(value) if name == "path" and value is not None else value
    return payload


def render_handoff(handoff: object | None) -> str:
    payload = handoff_payload(handoff)
    if payload is None:
        return "无 Worktree 交接信息。"
    return "; ".join(f"{key}={value}" for key, value in payload.items())


def render_usage(usage) -> str:
    if usage is None:
        return "不可用"
    values = usage.to_dict()
    return " ".join(
        f"{name}={'不可用' if value is None else value}"
        for name, value in values.items()
    )
