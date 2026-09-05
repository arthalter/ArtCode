from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any


def encode_record(sequence: int, payload: dict[str, Any]) -> bytes:
    body = {"version": 1, "sequence": sequence, "payload": payload}
    canonical = json.dumps(
        body, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    envelope = {**body, "sha256": hashlib.sha256(canonical).hexdigest()}
    return (
        json.dumps(envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def decode_record(line: bytes) -> tuple[int, dict[str, Any]]:
    raw = json.loads(line.decode("utf-8"))
    if not isinstance(raw, dict) or set(raw) != {"version", "sequence", "payload", "sha256"}:
        raise ValueError("记录 envelope 字段无效。")
    if raw["version"] != 1 or isinstance(raw["sequence"], bool) or not isinstance(raw["sequence"], int):
        raise ValueError("记录版本或序号无效。")
    if not isinstance(raw["payload"], dict) or not isinstance(raw["sha256"], str):
        raise ValueError("记录 payload 或校验和无效。")
    body = {key: raw[key] for key in ("version", "sequence", "payload")}
    canonical = json.dumps(
        body, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    if hashlib.sha256(canonical).hexdigest() != raw["sha256"]:
        raise ValueError("记录校验和不匹配。")
    return raw["sequence"], raw["payload"]


def append_record(path: Path, data: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError("同步追加没有取得进展。")
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)


def recover_lines(path: Path) -> tuple[list[bytes], tuple[str, ...]]:
    data = path.read_bytes() if path.exists() else b""
    issues: list[str] = []
    if data and not data.endswith(b"\n"):
        boundary = data.rfind(b"\n") + 1
        with path.open("r+b") as handle:
            handle.truncate(boundary)
            handle.flush()
            os.fsync(handle.fileno())
        data = data[:boundary]
        issues.append("已修复不完整的 Transcript 尾部。")
    return data.splitlines(), tuple(issues)
