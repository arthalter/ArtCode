from __future__ import annotations


def split_command(text: str) -> tuple[str, str]:
    command, separator, rest = text.strip().partition(" ")
    return command.casefold(), rest.strip() if separator else ""


HELP = """ArtCode commands:
/help
/plan <goal>
/act [additional constraints]
/compact
/permissions [default|edit|full]
/sandbox [auto|ask|off]
/skills | /skill <name> [input] | /clear
/tasks | /task <task-id> | /task-background <task-id> | /task-cancel <task-id>
/worktree-discard <task-id>
/status | /session | /memory | /worktrees
/exit"""
