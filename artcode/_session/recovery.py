from __future__ import annotations

from pathlib import Path

from artcode.core.session import SessionCorrupt, TranscriptFact

from .storage import decode_record, recover_lines
from .transcript import fact_from_payload


def recover_transcript(path: Path) -> tuple[tuple[TranscriptFact, ...], int, tuple[str, ...]]:
    lines, tail_issues = recover_lines(path)
    facts: list[TranscriptFact] = []
    issues = list(tail_issues)
    highest_sequence = 0
    for line_number, line in enumerate(lines, 1):
        try:
            sequence, payload = decode_record(line)
        except (UnicodeDecodeError, ValueError) as exc:
            issues.append(f"已隔离第 {line_number} 条损坏记录：{exc}")
            continue
        if sequence <= highest_sequence:
            issues.append(f"已隔离第 {line_number} 条非递增序号记录。")
            continue
        highest_sequence = sequence
        try:
            fact = fact_from_payload(payload)
        except SessionCorrupt as exc:
            issues.append(str(exc) + "；已回退到最近安全前缀。")
            break
        except ValueError as exc:
            issues.append(f"已隔离第 {line_number} 条非法记录：{exc}")
            continue
        facts.append(fact)
    return tuple(facts), highest_sequence + 1, tuple(issues)
