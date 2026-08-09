from __future__ import annotations

from collections.abc import Iterable


def split_bytes(payload: bytes, cut_points: Iterable[int]) -> tuple[bytes, ...]:
    """Split payload at validated byte offsets without losing or duplicating bytes."""

    points = sorted(set(cut_points))
    if any(point <= 0 or point >= len(payload) for point in points):
        raise ValueError("cut points must be inside the payload")
    boundaries = (0, *points, len(payload))
    return tuple(payload[start:end] for start, end in zip(boundaries, boundaries[1:]))


def sse_event(*data_lines: str, event: str | None = None) -> bytes:
    lines: list[str] = []
    if event is not None:
        lines.append(f"event: {event}")
    lines.extend(f"data: {line}" for line in data_lines)
    return ("\n".join(lines) + "\n\n").encode()
